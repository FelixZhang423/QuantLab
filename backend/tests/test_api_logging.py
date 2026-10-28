"""后端日志落盘（`api/logging_setup.py`）的测试。

覆盖三件事：
1. 路径与开关：`QL_API_LOG` / `QL_API_LOG_DIR` / 显式参数的优先级，文件名带日期。
2. 记录真的落进两个**分开**的文件：普通日志 -> `api_<日期>.log`，
   访问日志 -> `api_access_<日期>.log`（互不串台）。
3. 配置文件是 uvicorn 默认那份的拷贝：改它不能污染 `uvicorn.config.LOGGING_CONFIG`。

注意 `dictConfig` 会**替换** root 与 `uvicorn.*` 上已有的 handler，所以每个用例
都在 tearDown 里做快照还原，并在恢复前显式关掉新建的文件 handler（Windows 上
文件被占着时临时目录删不掉）。其它 170+ 个用例不能被这里搞脏。
"""
import contextlib
import io
import logging
import logging.config
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import uvicorn

from api import logging_setup

STAMP = "2026-10-15"


class LoggingSetupTestCase(unittest.TestCase):
    """公共脚手架：临时目录 + 全局 logging 状态快照/还原。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log_dir = Path(tmp.name) / "logs"  # 故意不存在：验证会自动建目录

        self._saved_root = (list(logging.getLogger().handlers), logging.getLogger().level)
        self._saved = {
            name: (
                list(logging.getLogger(name).handlers),
                logging.getLogger(name).level,
                logging.getLogger(name).propagate,
            )
            for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
        }
        self._file_handlers = []

    def tearDown(self):
        for handler in self._file_handlers:
            handler.close()
        root = logging.getLogger()
        root.handlers[:] = self._saved_root[0]
        root.setLevel(self._saved_root[1])
        for name, (handlers, level, propagate) in self._saved.items():
            logger = logging.getLogger(name)
            logger.handlers[:] = handlers
            logger.setLevel(level)
            logger.propagate = propagate

    # -- 工具 ---------------------------------------------------------------

    def apply(self, paths):
        """按生产里的方式配好日志（dictConfig），并记下新建的文件 handler。"""
        config = logging_setup.uvicorn_log_config(paths)
        logging.config.dictConfig(config)
        seen = {id(handler) for handler in self._file_handlers}
        for logger in (logging.getLogger(), logging.getLogger("uvicorn"), logging.getLogger("uvicorn.access")):
            for handler in logger.handlers:
                if isinstance(handler, logging.FileHandler) and id(handler) not in seen:
                    seen.add(id(handler))
                    self._file_handlers.append(handler)
        return config

    def read(self, path):
        return Path(path).read_text(encoding="utf-8").splitlines()


class ConfigureLoggingTests(LoggingSetupTestCase):
    def test_paths_are_dated_and_dir_is_created(self):
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)

        self.assertEqual(paths.directory, self.log_dir)
        self.assertEqual(paths.app.name, f"api_{STAMP}.log")
        self.assertEqual(paths.access.name, f"api_access_{STAMP}.log")
        self.assertTrue(self.log_dir.is_dir())  # 不存在的目录要自动建出来

    def test_default_dir_is_outputs_logs(self):
        from api import logging_setup as module

        self.assertEqual(module.DEFAULT_LOG_DIR, module.PROJECT_ROOT / "outputs" / "logs")
        self.assertEqual(module.PROJECT_ROOT.name, "backend")

    def test_env_switches_logging_off(self):
        for value in ("0", " false ", "False", "no", "NO", "off"):
            with mock.patch.dict(os.environ, {"QL_API_LOG": value}):
                self.assertFalse(logging_setup.logging_enabled(), value)
                self.assertIsNone(logging_setup.configure_logging(self.log_dir))
        self.assertFalse(self.log_dir.exists())  # 关掉了就连目录都不建

    def test_empty_env_value_means_default_on(self):
        """与 `QL_CH_PREWARM` 的既有约定一致：只认 0/false/no/off，空串算没设。"""
        with mock.patch.dict(os.environ, {"QL_API_LOG": ""}):
            self.assertTrue(logging_setup.logging_enabled())

    def test_logging_is_on_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QL_API_LOG", None)
            self.assertTrue(logging_setup.logging_enabled())
        with mock.patch.dict(os.environ, {"QL_API_LOG": "1"}):
            self.assertTrue(logging_setup.logging_enabled())
        with mock.patch.dict(os.environ, {"QL_API_LOG": "true"}):
            self.assertTrue(logging_setup.logging_enabled())

    def test_log_dir_env_and_explicit_param(self):
        env_dir = Path(self.log_dir).with_name("from_env")
        with mock.patch.dict(os.environ, {"QL_API_LOG_DIR": str(env_dir)}):
            self.assertEqual(logging_setup.resolve_log_dir(), env_dir)
            # 显式参数优先于环境变量
            self.assertEqual(logging_setup.resolve_log_dir(self.log_dir), self.log_dir)

    def test_describe_mentions_files(self):
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        text = logging_setup.describe(paths)
        self.assertIn(paths.app.name, text)
        self.assertIn(paths.access.name, text)
        self.assertIn("QL_API_LOG=0", logging_setup.describe(None))

    def test_describe_is_ascii_only(self):
        """这两行会打到控制台；Windows 默认代码页下中文是乱码，所以只允许 ASCII。"""
        paths = logging_setup.LogPaths(  # 写死路径，免得临时目录名里带非 ASCII 干扰断言
            directory=Path("C:/logs"),
            app=Path("C:/logs/api_2026-10-15.log"),
            access=Path("C:/logs/api_access_2026-10-15.log"),
        )
        for text in (logging_setup.describe(paths), logging_setup.describe(None)):
            text.encode("ascii")


class LogConfigTests(LoggingSetupTestCase):
    def test_disabled_returns_uvicorn_default_config_not_none(self):
        """关掉落盘时**不能**返回 None。

        `uvicorn.Config(log_config=None)` 不是「用默认配置」，而是完全跳过
        `configure_logging()`：真启动过一次，控制台连启动横幅都没有（只剩访问日志
        靠 lastResort 漏不出来）。必须返回 uvicorn 自带那份配置。
        """
        config = logging_setup.uvicorn_log_config(None)

        self.assertIsNotNone(config)
        self.assertIn("uvicorn.access", config["loggers"])
        self.assertIn("access", config["handlers"])
        # 没有任何文件 handler
        for name, handler in config["handlers"].items():
            self.assertNotIn("RotatingFileHandler", handler["class"], name)
        self.assertNotIn("root", config)  # 与 uvicorn 自带配置一致：应用日志此时不额外接管

    def test_does_not_mutate_uvicorn_default_config(self):
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        logging_setup.uvicorn_log_config(paths)

        default = uvicorn.config.LOGGING_CONFIG
        self.assertNotIn("file_app", default["handlers"])
        self.assertNotIn("file_access", default["handlers"])
        self.assertNotIn("root", default)
        self.assertNotIn("file_app", default["loggers"]["uvicorn"]["handlers"])
        self.assertNotIn("file_access", default["loggers"]["uvicorn.access"]["handlers"])

    def test_keeps_uvicorn_formatter_and_handler_names(self):
        """uvicorn 自己会往 formatters.default/access 里写 use_colors，这两项必须在。"""
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        config = logging_setup.uvicorn_log_config(paths)

        for key in ("default", "access", "file_app", "file_access", "console"):
            self.assertIn(key, config["formatters"])
        self.assertEqual(config["handlers"]["default"]["formatter"], "default")
        self.assertEqual(config["handlers"]["access"]["formatter"], "access")

    def test_file_handlers_are_windows_safe_rotating_utf8(self):
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        config = logging_setup.uvicorn_log_config(paths)

        for name, target in (("file_app", paths.app), ("file_access", paths.access)):
            handler = config["handlers"][name]
            self.assertEqual(handler["class"], "logging.handlers.RotatingFileHandler")
            self.assertEqual(handler["filename"], str(target))
            self.assertEqual(handler["encoding"], "utf-8")
            self.assertEqual(handler["maxBytes"], logging_setup.MAX_BYTES)
            self.assertEqual(handler["backupCount"], logging_setup.BACKUP_COUNT)
            self.assertTrue(handler["delay"])

    def test_disabled_key_keeps_existing_loggers_alive(self):
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        config = logging_setup.uvicorn_log_config(paths)
        self.assertIs(config["disable_existing_loggers"], False)

    def test_routing(self):
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        config = logging_setup.uvicorn_log_config(paths)

        # uvicorn 自己的启动/错误 -> 应用日志文件；应用 logger -> 根 -> 同一文件
        self.assertIn("file_app", config["loggers"]["uvicorn"]["handlers"])
        self.assertIn("file_app", config["root"]["handlers"])
        self.assertIn("console", config["root"]["handlers"])
        # 访问日志只进访问文件，不混进应用日志
        self.assertIn("file_access", config["loggers"]["uvicorn.access"]["handlers"])
        self.assertNotIn("file_access", config["root"]["handlers"])
        self.assertNotIn("file_app", config["loggers"]["uvicorn.access"]["handlers"])


class WritingTests(LoggingSetupTestCase):
    def test_nothing_is_created_before_the_first_record(self):
        """delay=True：没日志就不该出现空文件。"""
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        self.apply(paths)

        self.assertFalse(paths.app.exists())
        self.assertFalse(paths.access.exists())

    def test_app_and_access_records_land_in_separate_files(self):
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        self.apply(paths)

        logging.getLogger("uvicorn").info("Started server process [1234]")
        logging.getLogger("uvicorn.error").error("应用启动失败：数据库连不上")
        logging.getLogger("custom_bt.demo").info("回测跑完了")
        # 完全照抄 uvicorn 自己打访问日志的形状（httptools_impl.py 里那句）：
        # 位置参数，不是 extra={...} —— 见下面 test_access_formatter_handles_uvicorn_shape
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:58678",
            "GET",
            "/api/health",
            "1.1",
            200,
        )

        app_text = "\n".join(self.read(paths.app))
        access_text = "\n".join(self.read(paths.access))

        # 应用日志：uvicorn 的、应用自己的、报错都在一起
        self.assertIn("Started server process [1234]", app_text)
        self.assertIn("应用启动失败：数据库连不上", app_text)
        self.assertIn("回测跑完了", app_text)
        self.assertIn("ERROR", app_text)  # 级别列在
        self.assertIn("custom_bt.demo", app_text)  # 记录来源列在
        # 访问日志不串进应用日志
        self.assertNotIn("/api/health", app_text)

        # 访问日志：一行一次请求，含客户端地址与状态码
        self.assertIn("GET /api/health HTTP/1.1", access_text)
        self.assertIn("127.0.0.1:58678", access_text)
        self.assertIn("200", access_text)
        self.assertNotIn("Started server process", access_text)

    def test_access_formatter_handles_uvicorn_shape(self):
        """访问日志必须用 `uvicorn.logging.AccessFormatter`。

        曾经用普通 Formatter + `%(client_addr)s`：单元测试里自己塞 extra 能过，真跑起来
        却整行丢失（uvicorn 传的是位置参数），文件 0 字节、stderr 刷 "--- Logging error ---"。
        这里既查配置，也查真格式化的结果。
        """
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        config = logging_setup.uvicorn_log_config(paths)

        self.assertEqual(
            config["formatters"]["file_access"]["()"], "uvicorn.logging.AccessFormatter"
        )
        self.assertIs(config["formatters"]["file_access"]["use_colors"], False)

        self.apply(paths)
        # logging 丢弃记录时是把 "--- Logging error ---" 直接写 sys.stderr 的，
        # 所以要把 stderr 接住才算真的断言了「这行没被丢掉」。
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            logging.getLogger("uvicorn.access").info(
                '%s - "%s %s HTTP/%s" %d', "127.0.0.1:58678", "GET", "/api/health", "1.1", 404
            )

        self.assertNotIn("Logging error", buffer.getvalue())
        text = "\n".join(self.read(paths.access))
        self.assertIn("GET /api/health HTTP/1.1", text)
        self.assertIn("127.0.0.1:58678", text)
        self.assertIn("404", text)
        self.assertNotIn("\x1b[", text)  # 文件里不能有 ANSI 颜色码

    def test_lines_are_timestamped(self):
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        self.apply(paths)

        logging.getLogger("custom_bt.demo").info("带时间戳")
        line = self.read(paths.app)[0]

        stamp = line.split("\t")[0]
        # 形如 2026-10-15 14:03:21，别写死具体时间
        self.assertEqual(len(stamp), 19)
        self.assertEqual(stamp[4], "-")
        self.assertEqual(stamp[10], " ")
        self.assertEqual(stamp[13], ":")

    def test_utf8_round_trip_of_chinese(self):
        """中文必须原样写进文件 —— 命令行里传中文会变 GBK，日志文件不能再踩一次。"""
        paths = logging_setup.configure_logging(self.log_dir, enabled=True, stamp=STAMP)
        self.apply(paths)

        logging.getLogger("custom_bt.demo").warning("中文：沪深300 成分股「贵州茅台」600519")
        raw = Path(paths.app).read_bytes()

        self.assertIn("贵州茅台".encode("utf-8"), raw)
        self.assertIn('中文：沪深300 成分股「贵州茅台」600519', "\n".join(self.read(paths.app)))


if __name__ == "__main__":
    unittest.main()
