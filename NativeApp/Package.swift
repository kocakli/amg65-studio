// swift-tools-version:5.9
import PackageDescription
let package = Package(name: "AMG65Studio", platforms: [.macOS(.v14)], targets: [
    .systemLibrary(name: "CLibUSB", pkgConfig: "libusb-1.0", providers: [.brew(["libusb"])]),
    .executableTarget(name: "AMG65Studio", dependencies: ["CLibUSB"], resources: [.copy("Resources/localizations")], linkerSettings: [.linkedFramework("IOKit")]),
])
