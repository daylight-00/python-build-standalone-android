"""Host-only configuration used while producing Android distributions."""

from __future__ import annotations


def build_python_environment(
    environment: dict[str, str], *, current_host_tag: str
) -> tuple[dict[str, str], dict[str, str]]:
    """Return the environment and recorded cache overrides for build Python.

    Bionic can export functions that its ordinary host-compiler header view
    does not declare. Autoconf's link-only checks then succeed, but CPython's
    ``-Werror=implicit-function-declaration`` build fails when it calls them.
    Disable only the affected native build-interpreter probes; the cross-
    compiled target keeps its own API-aware feature checks.
    """
    result = dict(environment)
    cache: dict[str, str] = {}
    if current_host_tag.startswith("android-"):
        cache.update(
            {
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
        )
        result.update(cache)
    return result, cache


__all__ = ["build_python_environment"]
