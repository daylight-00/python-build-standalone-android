/* Interpreter frontend for the Android distributions.
 *
 * The official Python.org Android package is embedding-oriented and ships no
 * interpreter executable, so one is built here. This is the POSIX-equivalent
 * of CPython's own Programs/python.c and is modelled on it; that file is
 * covered by the Python Software Foundation License 2.0 (LICENSE.cpython.txt).
 */
#include <Python.h>
int main(int argc, char **argv) { return Py_BytesMain(argc, argv); }
