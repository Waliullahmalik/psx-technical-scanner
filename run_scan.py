import argparse
from pathlib import Path
import pandas as pd
from scanner import scan_folder
p=argparse.ArgumentParser();p.add_argument('--max-age-days',type=int,default=7);p.add_argument('--data',default='data');args=p.parse_args()
root=Path(__file__).resolve().parent
universe=pd.read_csv(root/'kse100_symbols.csv').Symbol.astype(str).str.upper().tolist()
universe=list(dict.fromkeys(universe+[x.stem.upper() for x in (root/args.data).glob('*.csv')]))
r,loaded=scan_folder(root/args.data,universe,max_age_days=args.max_age_days)
out=root/'output';out.mkdir(exist_ok=True);r.to_csv(out/'screening.csv',index=False)
print(f'{len(loaded)} CSVs loaded; {(r.Status.isin(["EARLY_WATCH","BREAKOUT_CONFIRMED","DEVELOPING","WEAK"])).sum()} usable; {sum(r.Status=="EARLY_WATCH")} early watch; {sum(r.Status=="BREAKOUT_CONFIRMED")} breakouts')
print(r[r.Status.isin(['EARLY_WATCH','BREAKOUT_CONFIRMED'])][['Symbol','Status','Score','Close','Entry Trigger','Stop Loss','Target 2R','RSI14','Vol Ratio']].to_string(index=False))
print('Saved:',out/'screening.csv')
