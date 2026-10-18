"""Repair Cython's signed-long conversion in the private Windows build.

The generated rand_r converts uint32 temper(seed) to C long before division.
Windows long is signed 32-bit: high values become negative, then item sampling
indexes negative rows. Use unsigned shift, equivalent to uint32 // 2, instead.
Only the experiment-local extension is rebuilt; system packages are untouched.
Requires MSVC Build Tools, NumPy, setuptools and a private lightfm-next install.
"""
from pathlib import Path
import re
import argparse

import numpy
from setuptools import Extension, setup


HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument("--openmp",action="store_true")
args=parser.parse_args()
module="_lightfm_fast_openmp" if args.openmp else "_lightfm_fast_no_openmp"
source=HERE/f".packages/lightfm/{module}.c"
text=source.read_text(encoding="utf-8")
pattern=r"__pyx_r = \(\(\(long\)(__pyx_f_\w+_temper\(\(__pyx_v_seed\[0\]\)\))\) / 2\);"
patched,count=re.subn(pattern,r"__pyx_r = (int)(\1 >> 1);",text)
if count!=1:
    raise RuntimeError(f"Expected exactly one known unsigned RNG conversion; found {count}")
build=HERE/"artifacts/native_build"
build.mkdir(parents=True,exist_ok=True)
target=build/source.name
target.write_text(patched,encoding="utf-8")
setup(
    name="cold-start-lightfm-windows-fix",
    ext_modules=[Extension(f"lightfm.{module}",[str(target)],include_dirs=[numpy.get_include()],extra_compile_args=["/O2"]+(["/openmp"] if args.openmp else []))],
    script_args=["build_ext","--build-lib",str(HERE/".packages"),"--build-temp",str(build/"temp")],
)
print("Rebuilt experiment-local LightFM with unsigned RNG sampling fix.")
