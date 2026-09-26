# gogdl's xdelta3 extension, from its pyproject [[tool.setuptools.ext-modules]] table, which
# needs setuptools >= 74.1 (the deckard snapshot has 69)
from setuptools import Extension, setup

setup(ext_modules=[Extension(
    "gogdl_xdelta3",
    sources=["gogdl_xdelta3.c", "xdelta3/xdelta3/xdelta3.c"],
    include_dirs=["xdelta3"],
    py_limited_api=True,
    extra_compile_args=["-DPy_LIMITED_API=0x03090000", "-DSIZEOF_SIZE_T=8", "-DSIZEOF_UNSIGNED_INT=4",
                        "-DSIZEOF_UNSIGNED_LONG=8", "-DSIZEOF_UNSIGNED_LONG_LONG=8",
                        "-DXD3_USE_LARGEFILE64=1", "-DXD3_ENCODER=0", "-DSECONDARY_DJW=0",
                        "-DSECONDARY_LZMA=0", "-DSHELL_TESTS=0"],
)])
