#!/usr/bin/env python3
"""Apply the Android system CA lookup patch to an OpenSSL 3.5.7 source tree."""

from __future__ import annotations

from pathlib import Path

EXACT_ANDROID_CA_DIR = "/apex/com.android.conscrypt/cacerts"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one source match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    root = Path.cwd()
    by_dir = root / "crypto/x509/by_dir.c"
    x509_def = root / "crypto/x509/x509_def.c"

    replace_once(
        x509_def,
        """#else
    return X509_CERT_DIR;
#endif
}
""",
        f"""#else
# if defined(__ANDROID__)
    return \"{EXACT_ANDROID_CA_DIR}\";
# else
    return X509_CERT_DIR;
# endif
#endif
}}
""",
    )

    replace_once(
        x509_def,
        """const char *X509_get_default_cert_file(void)
{
#if defined(_WIN32)
    RUN_ONCE(&openssldir_setup_init, do_openssldir_setup);
    return x509_cert_fileptr;
#else
    return X509_CERT_FILE;
#endif
}
""",
        f"""const char *X509_get_default_cert_file(void)
{{
#if defined(_WIN32)
    RUN_ONCE(&openssldir_setup_init, do_openssldir_setup);
    return x509_cert_fileptr;
#else
# if defined(__ANDROID__)
    return \"{EXACT_ANDROID_CA_DIR}/ca-certificates.crt\";
# else
    return X509_CERT_FILE;
# endif
#endif
}}
""",
    )

    replace_once(
        by_dir,
        """    int i, j, k;
    unsigned long h;
""",
        """    int i, j, k;
    int android_hash_attempt;
    unsigned long h, current_hash;
""",
    )
    replace_once(
        by_dir,
        """    h = X509_NAME_hash_ex(name, libctx, propq, &i);
    if (i == 0)
""",
        """    current_hash = X509_NAME_hash_ex(name, libctx, propq, &i);
    if (i == 0)
""",
    )
    replace_once(
        by_dir,
        """        if (type == X509_LU_CRL && ent->hashes) {
""",
        f"""        for (android_hash_attempt = 0; android_hash_attempt < 2;
             android_hash_attempt++) {{
            if (android_hash_attempt == 0) {{
                h = current_hash;
            }} else {{
                if (type != X509_LU_X509
                    || strcmp(ent->dir, \"{EXACT_ANDROID_CA_DIR}\") != 0)
                    break;
                h = X509_NAME_hash_old(name);
                if (h == current_hash)
                    break;
            }}

        if (type == X509_LU_CRL && ent->hashes) {{
""",
    )
    replace_once(
        by_dir,
        """        if (tmp != NULL) {
            ok = 1;
            ret->type = tmp->type;
            memcpy(&ret->data, &tmp->data, sizeof(ret->data));

            /*
             * Clear any errors that might have been raised processing empty
             * or malformed files.
             */
            ERR_clear_error();

            goto finish;
        }
""",
        """        if (tmp != NULL) {
            ok = 1;
            ret->type = tmp->type;
            memcpy(&ret->data, &tmp->data, sizeof(ret->data));

            /*
             * Clear any errors that might have been raised processing empty
             * or malformed files.
             */
            ERR_clear_error();

            goto finish;
        }
        }
""",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
