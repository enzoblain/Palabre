# Dependencies

Backend dependencies are frozen with [pip-tools](https://pip-tools.readthedocs.io) (versions and
hashes). Edit the readable `.in` files, never the generated `requirements*.txt`:

- `backend/requirements.in`: runtime dependencies (installed in the Docker image)
- `backend/requirements-dev.in`: test dependencies, on top of the runtime ones

pip-tools is a dev tool: it is not in the image. Install it where you work (`pip install pip-tools`),
then from `backend/`:

```sh
# Add a dependency: put it in the right .in file, then regenerate both files
pip-compile --generate-hashes --strip-extras requirements.in
pip-compile --generate-hashes --strip-extras requirements-dev.in

# Upgrade one runtime package (or --upgrade for all of them)
pip-compile --generate-hashes --strip-extras --upgrade-package fastapi requirements.in
pip-compile --generate-hashes --strip-extras requirements-dev.in

# Upgrade a test-only package (pytest...)
pip-compile --generate-hashes --strip-extras --upgrade-package pytest requirements-dev.in
```

Always compile `requirements.in` first: the dev file is constrained by it, so both stay on the same
versions. Compile on Linux with Python 3.12 (as the image and the CI): platform markers can differ elsewhere. Commit the `.in` and `.txt` files together.
Installs use `pip install --require-hashes -r ...`.

Dependabot opens a weekly grouped PR on `dev` for the backend locks. How it orders the two
compilations is not guaranteed, so CI installs both locks in one `pip install`: a PR where they pin
different versions fails. If that happens, run the compile commands above by hand.
