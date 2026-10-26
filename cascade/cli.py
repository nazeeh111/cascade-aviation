from __future__ import annotations
import argparse
import json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description='CASCADE: reproducible public-data disruption research')
    p.add_argument('command',choices=['quickstart','warehouse','analyze','forecast','simulate','export','all'])
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=p.parse_args();root=args.root.resolve()
    from cascade.warehouse import build,connect
    if args.command in ('quickstart','warehouse','all'):
        result=build(root,quickstart=args.command=='quickstart'); print(json.dumps(result,indent=2))
    if args.command=='quickstart':
        print('Real-data quickstart warehouse verified. Annual forecasting requires the full-year download; no small-sample model metrics are substituted.')
        return
    c=connect(root)
    try:
        if args.command in ('analyze','all'):
            from cascade.analyze import run,profile
            run(c,root)
            c.close()
            print(json.dumps(profile(None,root),indent=2,default=str))
            c=connect(root)
        if args.command in ('forecast','all'):
            from cascade.forecast import run
            c.execute('BEGIN')
            try:
                result=run(c,root)
                c.execute('COMMIT')
            except BaseException:
                c.execute('ROLLBACK')
                raise
            print(json.dumps(result['models'],indent=2))
        if args.command in ('simulate','all'):
            from cascade.simulate import run
            c.execute('BEGIN')
            try:
                result=run(c,root)
                c.execute('COMMIT')
            except BaseException:
                c.execute('ROLLBACK')
                raise
            print(json.dumps(result['replay'],indent=2))
        if args.command in ('export','all'):
            from cascade.export import run
            result=run(c,root);print(json.dumps(result,indent=2))
    finally:
        c.close()

if __name__=='__main__':
    main()
