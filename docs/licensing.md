# Licensing review

The repository does not currently contain a project licence. This PR does not
assign a licence or claim redistribution rights on the owner's behalf. The
owner must choose and add an appropriate licence before distributing releases.
The wheel therefore omits an invented licence declaration.

The runtime dependencies retain their upstream licences: requests (Apache-2.0),
python-dotenv (BSD-3-Clause), boto3/botocore/s3transfer (Apache-2.0), and Pillow
(HPND with its bundled third-party notices). Consult the installed distributions'
licence/notice files when redistributing them; this list is not a replacement for
those notices. No model weights, remote content or provider SDK source is
vendored into this repository.

The `auth_server` submodule is an independently maintained dependency at its
existing commit. This PR does not change its contents, pin or licensing, and it
is not included in the Python wheel. Its licence must be checked separately if
it is distributed. Developer/test tools are also installed independently rather
than included in the application wheel.
