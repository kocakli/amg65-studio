#!/usr/bin/env python3
"""Compile local translation source tables. No network or external dependencies."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
CODES=('tr','en','es','zh-Hans','ja')
tables={code:{} for code in CODES}
for filename,columns in [('localization_source.tsv',5),('localization_technical.tsv',6)]:
    for number,line in enumerate((ROOT/'Resources'/filename).read_text().splitlines(),1):
        if not line.strip(): continue
        row=[field.replace('\\n','\n') for field in line.split('\t')]
        if len(row)!=columns: raise ValueError(f'{filename}:{number}: expected{columns}fields,got{len(row)}')
        key=row[0]
        values=row if columns==5 else row[1:]
        for code,value in zip(CODES,values):
            if key in tables[code]: raise ValueError(f'Duplicate key: {key}')
            tables[code][key]=value
folder=ROOT/'Sources/AMG65Studio/Resources/localizations'
folder.mkdir(parents=True,exist_ok=True)
for code,table in tables.items():
    (folder/(code+'.json')).write_text(json.dumps(table,ensure_ascii=False,indent=2)+'\n')
print(f'{len(tables["tr"])} native strings × {len(CODES)} languages')
