import sys
sys.path.insert(0, '.')
import pandas as pd

xls = pd.ExcelFile(r'C:\Users\wangys38\Downloads\Santos_26_SWPD_Workbook.xlsx')
df = pd.read_excel(xls, sheet_name='Schedule', header=None)

print(f"Schedule sheet: {df.shape[0]} rows x {df.shape[1]} cols")
print()
print("前15行:")
for i in range(min(15, len(df))):
    row = df.iloc[i]
    vals = []
    for j in range(min(15, len(row))):
        v = row.iloc[j]
        if pd.notna(v):
            vals.append(f"[{j}]={str(v)[:20]}")
    print(f"  Row {i}: {' | '.join(vals)}")
