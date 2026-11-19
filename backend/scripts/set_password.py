
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.meta import init_db, new_session
from app.models.rbac import User
from app.rbac.security import hash_password, password_ok, random_password


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    generate = "--generate" in sys.argv[1:]
    username = args[0] if args else "admin"
    init_db()
    session = new_session()
    try:
        u = session.query(User).filter_by(username=username).first()
        if not u:
            print(f"用户不存在: {username}")
            return 1
        if generate:
            pwd = random_password()
        else:
            pwd = getpass.getpass(f"为 {username} 输入新口令: ")
            ok, why = password_ok(pwd)
            if not ok:
                print(f"口令不符合要求: {why}")
                return 1
            if getpass.getpass("再输入一次: ") != pwd:
                print("两次输入不一致")
                return 1
        u.pwd_hash = hash_password(pwd)
        u.failed_count = 0
        u.locked_until = None
        session.commit()
        if generate:
            print(f"已为 {username} 生成一次性口令（仅本次显示，登录后请立即修改）: {pwd}")
        else:
            print(f"已更新 {username} 的口令")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

