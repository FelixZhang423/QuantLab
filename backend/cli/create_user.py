import argparse
from getpass import getpass

from repositories.auth_store import initialize, password_hash, transaction


def main():
    parser = argparse.ArgumentParser(description="创建 QuantLab 登录账号")
    parser.add_argument("username")
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=("researcher", "admin"), default="researcher")
    args = parser.parse_args()
    username = args.username.strip()
    name = args.name.strip()
    if not (1 <= len(username) <= 100 and 1 <= len(name) <= 100):
        parser.error("用户名及姓名长度应为 1 至 100 个字符")
    password = getpass("密码（至少 12 个字符）: ")
    if not 12 <= len(password) <= 256 or password != getpass("确认密码: "):
        parser.error("密码长度不符合要求或两次输入不一致")
    hashed = password_hash(password)
    with transaction() as cursor:
        initialize(cursor)
        cursor.execute(
            "INSERT INTO ql_auth_users (username, display_name, password_hash, role) VALUES (%s,%s,%s,%s)",
            (username, name, hashed, args.role),
        )
    print(f"已创建账号 {username}")


if __name__ == "__main__":
    main()
