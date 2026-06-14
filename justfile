# CEC Tech Topics — run `just` to see available recipes

_default:
    @just --list

# check python and create the database — all you need after a clone
setup:
    @python3 -c "import sys; v = sys.version_info; assert v >= (3, 9), 'need Python 3.9+, found %d.%d' % v[:2]; print('python %d.%d.%d ok' % v[:3])"
    @python3 -c "import db; db.connect().close(); print('database ready:', db.DB_PATH)"
    @echo "setup complete — run 'just dev' to start the site"

# run the review site, reachable on the LAN / tailscale (localhost only: just dev 127.0.0.1)
dev host="0.0.0.0" port="8765":
    python3 server.py --host {{host}} --port {{port}}
