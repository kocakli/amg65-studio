"""Compile the production send() method with fake IOHID and response delivery.

No hardware import, USB handle, installed helper or provider credential is used.
The source extraction keeps these assertions attached to the shipped ACK logic.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("xcrun"), "macOS Swift SDK required")
class HelperACKChecks(unittest.TestCase):
    def test_production_ack_status_checksum_and_fault_latch(self):
        source = (ROOT / "AMG65HID.swift").read_text()
        start = source.index("    func send(")
        end = source.index("\n    func command(", start)
        method = source[start:end]
        harness = r'''
import Foundation
struct BridgeError: Error, CustomStringConvertible {
    let description: String
    init(_ text: String) { description = text }
}
let kIOHIDReportTypeOutput = 0
let kIOReturnSuccess: Int32 = 0
final class FakeDevice { var writes = 0 }
func IOHIDDeviceSetReport(_ device: FakeDevice, _ type: Int, _ id: Int,
                         _ report: inout [UInt8], _ count: Int) -> Int32 {
    device.writes += 1
    return kIOReturnSuccess
}
final class Probe {
    var healthy = true
    var replies = [[UInt8]]()
    var packets = 0
    let device = FakeDevice()
    var pending: [[UInt8]]
    init(_ pending: [[UInt8]]) { self.pending = pending }
    func pump(_ seconds: Double) {
        replies.append(contentsOf: pending)
        pending.removeAll()
        if replies.isEmpty { Thread.sleep(forTimeInterval: 0.001) }
    }
__PRODUCTION_METHOD__
}
struct Result: Encodable { let name: String; let passed: Bool }
var results = [Result]()
func check(_ name: String, _ response: [[UInt8]], expected: UInt8 = 0x02,
           flush: Bool = false, checksum: UInt16? = nil,
           accepts: Bool, errorContains: String? = nil) {
    let probe = Probe(response)
    var accepted = false, message = ""
    do { try probe.send([4, expected], expected: expected, flush: flush, checksum: checksum); accepted = true }
    catch { message = String(describing: error) }
    var passed = accepted == accepts && probe.healthy == accepts
        && probe.packets == (accepts ? 1 : 0) && probe.device.writes == 1
    if let errorContains { passed = passed && message.contains(errorContains) }
    if !accepts {
        // Even a later valid ACK cannot reopen this failed connection or resend.
        probe.pending = [[4, expected, 0, 1, 0x34, 0x12]]
        do { try probe.send([4, expected], expected: expected); passed = false }
        catch { passed = passed && probe.device.writes == 1 && !probe.healthy }
    }
    results.append(Result(name: name, passed: passed))
}
check("valid END", [[4, 2, 0, 1]], accepts: true)
check("valid checksum", [[4, 2, 0, 1, 0x34, 0x12]], checksum: 0x1234, accepts: true)
check("wrong checksum", [[4, 2, 0, 1, 0x35, 0x12]], checksum: 0x1234,
      accepts: false, errorContains: "checksum")
check("missing checksum", [[4, 2, 0, 1]], checksum: 0x1234,
      accepts: false, errorContains: "checksum")
check("reported END FF", [[4, 2, 0, 0xff, 0, 0, 0, 0]],
      accepts: false, errorContains: "USB rejected opcode 0x02 with status 0xFF")
check("other rejection", [[4, 0x35, 0, 0]], expected: 0x35,
      accepts: false, errorContains: "USB rejected opcode 0x35 with status 0x00")
check("rejection before later OK", [[4, 2, 0, 0xff], [4, 2, 0, 1]],
      accepts: false, errorContains: "USB rejected")
check("unrelated rejection then expected ACK", [[4, 0x41, 0, 0xff], [4, 2, 0, 1]], accepts: true)
check("wrong envelope then expected ACK", [[4, 2, 1, 0xff], [4, 2, 0, 1]], accepts: true)
check("short envelope then expected ACK", [[4, 2, 0], [4, 2, 0, 1]], accepts: true)
check("zero flush remains scoped", [[0, 0, 0, 0xff]], expected: 0x41, flush: true, accepts: true)
check("zero flush rejected elsewhere", [[0, 0, 0, 0xff]], expected: 0x41,
      accepts: false, errorContains: "No ACK")
check("missing reply remains timeout", [], accepts: false, errorContains: "No ACK")
let data = try JSONEncoder().encode(results)
print(String(decoding: data, as: UTF8.self))
'''.replace("__PRODUCTION_METHOD__", method)
        with tempfile.TemporaryDirectory(prefix="amg65-ack-checks-") as temporary:
            directory = Path(temporary)
            swift = directory / "ACKChecks.swift"
            executable = directory / "ack-checks"
            swift.write_text(harness)
            subprocess.run(["xcrun", "swiftc", "-module-cache-path", str(directory / "modules"),
                            str(swift), "-o", str(executable)],
                           check=True, capture_output=True, text=True, timeout=120)
            completed = subprocess.run([str(executable)], check=True, capture_output=True,
                                       text=True, timeout=15)
        results = json.loads(completed.stdout)
        self.assertEqual(len(results), 13)
        for result in results:
            with self.subTest(result["name"]):
                self.assertTrue(result["passed"], result["name"])


if __name__ == "__main__":
    unittest.main()
