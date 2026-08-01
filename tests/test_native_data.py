"""Source-level tests for Android-native CA and timezone integration."""

from __future__ import annotations

import ast
import importlib.util
import io
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from pythonbuild.android_host import build_python_environment
from pythonbuild.native_data import apply_cpython_android_native_data

ROOT = Path(__file__).resolve().parent.parent


class AndroidPackedTimezoneTest(unittest.TestCase):
    def test_reads_one_member_without_extraction(self) -> None:
        module_path = ROOT / "patches/cpython/zoneinfo/_android.py"
        spec = importlib.util.spec_from_file_location("test_android_zoneinfo", module_path)
        assert spec is not None and spec.loader is not None
        module = cast(Any, importlib.util.module_from_spec(spec))
        spec.loader.exec_module(module)

        payload = b"TZif" + bytes(range(32))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tzdata"
            index_offset = 24
            data_offset = index_offset + 52
            final_offset = data_offset + len(payload)
            header = b"tzdata9999z\x00" + struct.pack(
                ">III", index_offset, data_offset, final_offset
            )
            record = struct.pack(
                ">40sIII", b"Etc/Test".ljust(40, b"\x00"), 0, len(payload), 0
            )
            path.write_bytes(header + record + payload)
            module._TZDATA_PATH = path

            loaded = module.load_tzdata("Etc/Test")
            self.assertIsInstance(loaded, io.BytesIO)
            self.assertEqual(loaded.read(), payload)
            self.assertEqual(module.available_timezones(), {"Etc/Test"})
            with self.assertRaises(FileNotFoundError):
                module.load_tzdata("Etc/Missing")
            with self.assertRaises(ValueError):
                module.load_tzdata("../Etc/Test")


class CPythonSourceIntegrationTest(unittest.TestCase):
    def test_applies_to_the_zoneinfo_source_seams(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            zoneinfo = source / "Lib/zoneinfo"
            zoneinfo.mkdir(parents=True)
            (zoneinfo / "_common.py").write_text(
                "def load_tzdata(key):\n    raise RuntimeError\n\n\n"
                "def load_data(fobj):\n    return fobj\n",
                encoding="utf-8",
            )
            (zoneinfo / "_tzpath.py").write_text(
                "import os\nimport sysconfig\n\n"
                "def _reset_tzpath(to=None, stacklevel=4):\n    global TZPATH\n"
                "    TZPATH = ()\n\n\n"
                "def reset_tzpath(to=None):\n    _reset_tzpath(to)\n\n\n"
                "def available_timezones():\n    return set()\n\n\n"
                "class InvalidTZPathWarning(RuntimeWarning):\n    pass\n\n\n"
                "TZPATH = ()\n_reset_tzpath(stacklevel=5)\n",
                encoding="utf-8",
            )

            records = apply_cpython_android_native_data(source)
            self.assertEqual(len(records), 5)
            self.assertTrue((zoneinfo / "_android.py").is_file())
            common = (zoneinfo / "_common.py").read_text(encoding="utf-8")
            tzpath = (zoneinfo / "_tzpath.py").read_text(encoding="utf-8")
            self.assertIn("_android.load_tzdata(key)", common)
            self.assertIn("_ANDROID_NATIVE_FALLBACK = not explicit", tzpath)
            self.assertIn("_android.available_timezones()", tzpath)
            self.assertNotIn(str(source), str(records))


class OpenSSLSourceIntegrationTest(unittest.TestCase):
    def test_patcher_is_exact_and_scoped_to_the_conscrypt_apex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "crypto/x509"
            target.mkdir(parents=True)
            (target / "x509_def.c").write_text(
                "const char *f(void) {\n#else\n    return X509_CERT_DIR;\n#endif\n}\n"
                "const char *X509_get_default_cert_file(void)\n{\n"
                "#if defined(_WIN32)\n"
                "    RUN_ONCE(&openssldir_setup_init, do_openssldir_setup);\n"
                "    return x509_cert_fileptr;\n"
                "#else\n    return X509_CERT_FILE;\n#endif\n}\n",
                encoding="utf-8",
            )
            (target / "by_dir.c").write_text(
                "int f(void) {\n"
                "    int i, j, k;\n    unsigned long h;\n"
                "    h = X509_NAME_hash_ex(name, libctx, propq, &i);\n"
                "    if (i == 0)\n        goto finish;\n"
                "        if (type == X509_LU_CRL && ent->hashes) {\n"
                "            k = 0;\n        }\n"
                "        if (tmp != NULL) {\n            ok = 1;\n"
                "            ret->type = tmp->type;\n"
                "            memcpy(&ret->data, &tmp->data, sizeof(ret->data));\n\n"
                "            /*\n"
                "             * Clear any errors that might have been raised processing empty\n"
                "             * or malformed files.\n             */\n"
                "            ERR_clear_error();\n\n            goto finish;\n        }\n"
                "finish:\n    return ok;\n}\n",
                encoding="utf-8",
            )
            patcher = ROOT / "patches/openssl/android-native-ca.py"
            subprocess.run([sys.executable, str(patcher)], cwd=root, check=True)
            result = (target / "by_dir.c").read_text(encoding="utf-8")
            defaults = (target / "x509_def.c").read_text(encoding="utf-8")
            exact = "/apex/com.android.conscrypt/cacerts"
            self.assertIn(f'strcmp(ent->dir, "{exact}")', result)
            self.assertIn("X509_NAME_hash_old(name)", result)
            self.assertIn(f'return "{exact}";', defaults)
            self.assertIn(f'return "{exact}/ca-certificates.crt";', defaults)


class NDKPrebuiltSelectionSourceTest(unittest.TestCase):
    def test_uses_the_selected_target_compiler_not_a_prebuilt_wildcard(self) -> None:
        dependencies = (ROOT / "pythonbuild/dependencies.py").read_text(encoding="utf-8")
        cpython_source = (ROOT / "pythonbuild/cpython_source.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def selected_toolchain_override()", dependencies)
        self.assertIn("command -v", dependencies)
        self.assertIn('${clang_triplet}${ANDROID_API_LEVEL}-clang', dependencies)
        self.assertIn("toolchain_bin: Path", dependencies)
        self.assertIn("str(toolchain_bin)", dependencies)
        self.assertIn("selected_toolchain_override()", cpython_source)
        self.assertIn("toolchain_bin=toolchain.readelf.parent", cpython_source)


class CPythonSourceExtractionPolicyTest(unittest.TestCase):
    def test_recreates_the_source_tree_before_applying_in_place_patches(self) -> None:
        path = ROOT / "pythonbuild/cpython_source.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_extract_source"
        )

        def fake_extract(_archive: Path, destination: Path) -> None:
            (destination / "Python-test").mkdir()

        namespace = {"Path": Path, "shutil": shutil, "safe_extract_tar": fake_extract}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"),
            namespace,
        )
        extract_source = namespace["_extract_source"]

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "source"
            destination.mkdir()
            stale = destination / "Python-test/Lib/zoneinfo/_android.py"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale", encoding="utf-8")

            root = extract_source(Path(temporary) / "source.tar.gz", destination)
            self.assertEqual(root, destination / "Python-test")
            self.assertFalse(stale.exists())


class AndroidBuildPythonConfigureTest(unittest.TestCase):
    def test_disables_only_broken_android_host_function_probes(self) -> None:
        base = {"PATH": "/host/bin", "ac_cv_func_other": "yes"}
        expected = {
            "ac_cv_func_close_range": "no",
            "ac_cv_func_copy_file_range": "no",
            "ac_cv_func_fexecve": "no",
            "ac_cv_func_getloadavg": "no",
            "ac_cv_func_getlogin_r": "no",
            "ac_cv_func_getpwent": "no",
            "ac_cv_func_preadv2": "no",
            "ac_cv_func_pthread_getname_np": "no",
            "ac_cv_func_pwritev2": "no",
            "ac_cv_func_sem_clockwait": "no",
        }

        android, cache = build_python_environment(
            base, current_host_tag="android-aarch64"
        )
        self.assertEqual(cache, expected)
        self.assertEqual({key: android[key] for key in expected}, expected)
        self.assertEqual(android["ac_cv_func_other"], "yes")
        for key in expected:
            self.assertNotIn(key, base)

        linux, cache = build_python_environment(
            base, current_host_tag="linux-aarch64"
        )
        self.assertEqual(cache, {})
        for key in expected:
            self.assertNotIn(key, linux)



class TargetHostIsolationSourceTest(unittest.TestCase):
    def test_target_recipes_drop_termux_search_paths_and_reject_host_sonames(self) -> None:
        dependencies = (ROOT / "pythonbuild/dependencies.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("TARGET_HOST_ENVIRONMENT_VARIABLES", dependencies)
        self.assertIn('"PREFIX"', dependencies)
        self.assertIn("environment.pop(variable, None)", dependencies)
        self.assertIn("elf_surface(path, readelf)", dependencies)
        self.assertIn("dependency objects require versioned libraries", dependencies)

    def test_native_ca_gate_verifies_the_lazy_default_store(self) -> None:
        qualify_path = ROOT / "qualify.py"
        qualify = qualify_path.read_text(encoding="utf-8")
        gate = (ROOT / "pythonbuild/qualification.py").read_text(encoding="utf-8")
        self.assertIn("X509_STORE_set_default_paths", qualify)
        self.assertIn('"ca_default_verify_pass"', qualify)
        self.assertIn("builtin-ca-unverified", qualify)
        self.assertIn('observed.get("ca_default_verify_pass")', gate)

        spec = importlib.util.spec_from_file_location("test_qualify_script", qualify_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        checks = {
            "identity": {
                "pass": True,
                "paths_within_prefix": True,
                "multiarch": "aarch64-linux-android",
                "prefix": "/runtime/python",
            },
            "extensions": {"pass": True, "failures": {}},
            "dlopen": {"pass": True},
            "subprocess": {"pass": True},
            "relocated_identity": {"pass": True, "prefix": "/relocated/python"},
            "pip": {"pass": True},
            "venv": {"pass": True},
            "runtime_data": {
                "pass": True,
                "ca_certificate_count": 0,
                "ca_default_verify_pass": True,
            },
        }
        self.assertTrue(
            module.evaluate(checks, None, builtin_runtime_data=True)["pass"]
        )


class HostToolOverrideSourceTest(unittest.TestCase):
    def test_lld_override_is_explicit_propagated_and_recorded(self) -> None:
        toolchain = (ROOT / "pythonbuild/toolchain.py").read_text(encoding="utf-8")
        dependencies = (ROOT / "pythonbuild/dependencies.py").read_text(
            encoding="utf-8"
        )
        cpython_source = (ROOT / "pythonbuild/cpython_source.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('os.environ.get("PBSA_LLD")', toolchain)
        self.assertIn('"lld_source": self.lld_source', toolchain)
        self.assertIn("def selected_linker_overrides()", dependencies)
        self.assertIn('environment["PBSA_LLD"] = str(lld)', dependencies)
        self.assertIn('environment["PBSA_LLD"] = str(lld)', cpython_source)
        self.assertIn('export LDFLAGS="-fuse-ld=$PBSA_LLD $LDFLAGS"', dependencies)

    def test_patchelf_override_is_explicit_validated_and_recorded(self) -> None:
        source = (ROOT / "pythonbuild/toolchain.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("PBSA_PATCHELF")', source)
        self.assertIn('"environment-override"', source)
        self.assertIn('"--page-size"', source)
        self.assertIn('"--version"', source)
        self.assertIn('"patchelf_source": self.patchelf_source', source)


if __name__ == "__main__":
    unittest.main()
