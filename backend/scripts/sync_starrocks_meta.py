import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.engine import meta_sync


def probe(con) -> None:
    rows = meta_sync.fetch_tables(con, None)
    print(f"[probe] {get_settings().starrocks_db}: {len(rows)} tables")
    for r in rows:
        print(f"  {r['table_name']:<40} rows≈{r['table_rows']:<10} {r['table_comment']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--sync", type=str, default="")
    ap.add_argument("--sync-all", action="store_true")
    ap.add_argument("--max-tables", type=int, default=20)
    args = ap.parse_args()

    try:
        if args.probe:
            con = meta_sync.connect()
            try:
                probe(con)
            finally:
                con.close()
        elif args.sync or args.sync_all:
            if args.sync_all:
                meta_sync.sync(max_tables=args.max_tables)
            else:
                names = [n.strip() for n in args.sync.split(",") if n.strip()]
                meta_sync.sync(names=names)
            print("[next] 需人工增强: 表/列中文别名、枚举字典(enum_dict)、dept_column 标注；然后设置 DATASOURCE_URL 指向 StarRocks")
        else:
            ap.print_help()
    except RuntimeError as e:
        raise SystemExit(str(e))