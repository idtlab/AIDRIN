#!/bin/bash
# Configure an AIDRIN CLI module (wrapper script + Lmod modulefile) that runs the `cli` image.
#
#   configure-module.sh SITE VERSION IMAGE ROOT
#
#   SITE     perlmutter (Shifter) or expanse (Singularity; experimental, not yet tested on Expanse)
#   VERSION  module version, e.g. 2026.09.1, or 2026.09.1-mcp to also expose aidrin-mcp
#   IMAGE    perlmutter: the Shifter image, e.g. docker:aidrin/aidrin:v2026.09.1
#            expanse:    absolute path to the .sif
#   ROOT     where to put it: your own dir (e.g. ~/aidrin-modules) or a shared, world-readable one
#
# Writes ROOT/aidrin/VERSION/bin/ and ROOT/modulefiles/aidrin/VERSION.lua.
# Then: module use ROOT/modulefiles && module load aidrin
set -euo pipefail

if [ $# -ne 4 ]; then
    if [ -f "$0" ]; then
        sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    else  # piped from curl
        echo "usage: configure-module.sh SITE VERSION IMAGE ROOT" >&2
    fi
    exit 2
fi
site=$1 version=$2 image=$3 root=$4

case $site in
    perlmutter)
        run="shifter --image=$(printf %q "$image")"
        load=""
        ;;
    expanse)
        [ -f "$image" ] || { echo "error: $image not found" >&2; exit 1; }
        run="singularity exec --bind /expanse $(printf %q "$image")"
        load='load("singularitypro")'
        echo "note: expanse support is experimental and not yet tested on Expanse itself" >&2
        ;;
    *)
        echo "error: unknown site '$site' (perlmutter or expanse)" >&2
        exit 2
        ;;
esac

prefix=$root/aidrin/$version
modfile=$root/modulefiles/aidrin/$version.lua
# Never change an installed version in place: compute nodes may cache it, and users may be
# mid-job. Install a new version instead.
if [ -e "$prefix" ] || [ -e "$modfile" ]; then
    echo "error: $prefix or $modfile already exists; install under a new version" >&2
    exit 1
fi

commands=(aidrin)
[[ $version == *-mcp ]] && commands+=(aidrin-mcp)

mkdir -p "$prefix/bin" "$(dirname "$modfile")"
for cmd in "${commands[@]}"; do
    # No --clearenv/--cleanenv: they drop SCRATCH, OMP_NUM_THREADS and SLURM_*. The image's own
    # ENV keeps host Python settings out (see the cli stage in docker/NERSC/Dockerfile).
    printf '#!/bin/bash\nexec %s /app/.venv/bin/%s "$@"\n' "$run" "$cmd" > "$prefix/bin/$cmd"
    chmod 755 "$prefix/bin/$cmd"
done

cat > "$modfile" <<EOF
help([[
AIDRIN $version: AI data readiness assessment, run from a container.

  aidrin list
  aidrin data-quality FILE
  aidrin run METRIC FILE [COLUMNS]
  aidrin batch CONFIG.yaml          (set image_dir: to a directory you own)

Docs: https://aidrin.readthedocs.io
]])
whatis("Name: AIDRIN")
whatis("Version: $version")
whatis("Description: AI data readiness assessment CLI")
whatis("URL: https://github.com/idtlab/AIDRIN")
whatis("License: BSD-3-Clause")
$load
prepend_path("PATH", "$prefix/bin")
EOF

chmod -R o+rX "$root/aidrin" "$root/modulefiles"
echo "installed: ${commands[*]} in $prefix/bin"
echo "modulefile: $modfile"
echo "then run: module use $root/modulefiles && module load aidrin/$version"
