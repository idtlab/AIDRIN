# AIDRIN as an HPC module

The `aidrin` CLI as `module load aidrin` on NERSC Perlmutter (Shifter), with SDSC Expanse
(Singularity) support in testing. The module is a one-line wrapper around the public `cli` image
(`aidrin/aidrin` on Docker Hub), built from `docker/NERSC/Dockerfile`. Nothing is installed
into a Python environment, and each user configures the module for themselves.

## Users: set up the module

### Perlmutter

```bash
shifterimg pull aidrin/aidrin:v2026.10.1
curl -sL https://raw.githubusercontent.com/idtlab/AIDRIN/develop/hpc/configure-module.sh \
    | bash -s perlmutter 2026.10.1 docker:aidrin/aidrin:v2026.10.1 ~/aidrin-modules
module use ~/aidrin-modules/modulefiles    # add this line to ~/.bashrc
module load aidrin
```

### Expanse (in testing)

Tested so far only against a local Apptainer + Lmod setup; SDSC is testing it on Expanse. Build
the image in an interactive job, not on a login node:

```bash
srun --account=<account> --partition=debug --nodes=1 --ntasks-per-node=4 --mem=16G \
    -t 00:30:00 --pty /bin/bash
module load singularitypro
export SINGULARITY_CACHEDIR=/scratch/$USER/job_$SLURM_JOB_ID
singularity pull ~/aidrin-2026.10.1.sif docker://aidrin/aidrin:v2026.10.1
curl -sL https://raw.githubusercontent.com/idtlab/AIDRIN/develop/hpc/configure-module.sh \
    | bash -s expanse 2026.10.1 ~/aidrin-2026.10.1.sif ~/aidrin-modules
module use ~/aidrin-modules/modulefiles    # add this line to ~/.bashrc
module load aidrin
```

#### Testing checklist for Expanse

1. Run the commands above. Note any step that fails, for example `module load singularitypro`
   not being found (then `module spider singularitypro`) or the `singularity pull`.
2. With the module loaded, from a directory on Lustre (for example
   `/expanse/lustre/scratch/$USER/temp_project`), run
   `curl -sLO https://raw.githubusercontent.com/idtlab/AIDRIN/develop/hpc/smoke-test.sh && bash smoke-test.sh`
   on a login node and inside an `srun` session. It prints `PASS`/`FAIL` per check.
3. Optional: repeat with the `-mcp` image (`v2026.10.1-mcp`, module version `2026.10.1-mcp`),
   which adds an `aidrin-mcp` check.
4. Report the full output of steps 1 and 2, plus `module list`, `singularity --version` and
   `time aidrin list`, in the GitHub issue or PR.

For a new release, run the same commands with the new version. Older versions stay available
until you delete their `~/aidrin-modules/aidrin/<ver>` and `modulefiles/aidrin/<ver>.lua`.
Use a `-mcp` version (image tag `v2026.10.1-mcp`, module version `2026.10.1-mcp`) to also get
`aidrin-mcp`.

A shared install works the same way: point `ROOT` at a world-readable directory, for example
`/global/common/software/<proj>/public`. Users outside the project also need
`chmod o+x /global/common/software/<proj>`, and only the owner of the project dir (usually the
PI) can run that; group write access is not enough.

## Maintainers: build and publish the image

From the repo root, at the release tag, publish both architectures (amd64 for HPC, arm64 for
Apple Silicon laptops):

```bash
docker buildx build --platform linux/amd64,linux/arm64 -f docker/NERSC/Dockerfile --target cli \
    -t aidrin/aidrin:v2026.10.1 --push .
docker buildx build --platform linux/amd64,linux/arm64 -f docker/NERSC/Dockerfile --target cli \
    --build-arg AIDRIN_CLI_EXTRAS="--extra mcp" -t aidrin/aidrin:v2026.10.1-mcp --push .
```

Image tags are the git release tag (`v2026.10.1`, plus `-mcp`), the same as the images in the
NERSC registry. Module versions drop the `v` (`2026.10.1`), matching `aidrin/_version.py`.
The `-mcp` image adds `aidrin-mcp` and the agentic stack (langchain, faiss, pymupdf). Never
retag a published version.

The image's entrypoint is `aidrin`, so `docker run --rm -v $PWD:$PWD -w $PWD aidrin/aidrin:<ver> list`
works. The module wrappers call `/app/.venv/bin/aidrin` explicitly, so Shifter and Singularity
don't depend on the entrypoint. `podman-hpc run` does honor it: pass only the arguments.

## Test

After `module load aidrin`, run `hpc/smoke-test.sh` from `$SCRATCH` on a login node and on a
compute node. It exits non-zero if any check fails.
