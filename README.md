# pycc-compiler

Compile Python to ELF on Termux (Cython `--embed` + clang/gcc).

```bash
pycc --help
```

## Install

```bash
pkg install clang python cython
pip install .
```

## Usage

```bash
# single file -> ./app (no .out suffix)
pycc app.py

# exact output name
pycc app.py -o myapp

# shared library (<module><EXT_SUFFIX>)
pycc app.py -so

# compile and run (temporary file; -o is ignored)
pycc app.py -run
```

## Directory modes

```bash
# every file in the directory -> its own executable
pycc --dir src/

# every Python file -> its own shared library
pycc -so --dir src/

# bundle the whole directory into one executable
pycc --dir-one src/

# bundle the whole directory into one shared library
pycc -so --dir-one src/
```

`-o` works with every mode:

```bash
pycc --dir src/ -o build/          # output directory for --dir
pycc --dir-one src/ -o myapp       # exact executable name
pycc -so --dir-one src/ -o mylib   # <name><EXT_SUFFIX>
```

### `--dir-one`

- The entry file is compiled with `cython --embed`.
- Every other `.py/.pyx` file is compiled as a normal Cython module.
- All generated C files are compiled to object files and linked into a single
  executable or shared library.
- Entry selection: `__main__.py`, then `main.py`, then `<directory name>.py`.
  Override it with `--entry <module>`.

For an executable, sibling modules are registered before `Py_Initialize`, so
`import sibling` keeps working. For a shared library, sibling imports are
resolved from the same `.so` via `ExtensionFileLoader`.

Only files directly inside the directory are included (no recursion). C/C++
files are compiled in `--dir` mode, but ignored by `--dir-one`.

In `--dir` mode each file is compiled on its own, so sibling `import`s are not
bundled; use `--dir-one` when the files depend on each other.

## Shell completions

```bash
# bash
pycc --completions bash > $PREFIX/share/bash-completion/completions/pycc

# zsh
pycc --completions zsh > $PREFIX/share/zsh/site-functions/_pycc

# fish
pycc --completions fish > $PREFIX/share/fish/vendor_completions.d/pycc.fish
```

## Options

| Option | Description |
| --- | --- |
| `-o, --output` | Exact output name (output directory with `--dir`) |
| `-O, --option` | Pass extra arguments to the compiler |
| `-B, --best` | Best optimization |
| `--python <ver>` | Python version to build against |
| `-so` | Build a shared library |
| `--dir` | Compile a directory file by file |
| `--dir-one, -one` | Bundle a directory into one output |
| `--entry <name>` | Entry module for `--dir-one` |
| `--site, -s` | Install the built `.so` to site-packages |
| `-run` | Compile to a temporary file and run (`-o` is ignored) |
| `-c` / `-cpp` | Generate C / C++ source |
| `-v` | Verbose mode (show commands) |
| `-q` | Quiet mode |
| `-###` | Show commands only |
| `--completions <sh>` | Print shell completions (`bash`/`zsh`/`fish`) |

## Environment

- `PYCC_PY_VERSION` — Python version
- `PYCC_EXT_SUFFIX` — override the C extension suffix

> Termux only.
