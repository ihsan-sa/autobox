"""Import before `lander`: pins admission's load and pressure to a calm host, so a busy real box (bwrap shows its
/proc/loadavg) cannot drop slots or start the overloaded re-plan mid-case. admission reads both at import."""
import os
import tempfile

_d = tempfile.mkdtemp(prefix="lander-calm-")
with open(os.path.join(_d, "loadavg"), "w") as f:
    f.write("0.5 0.5 0.5 1/100 1\n")
for _k in ("cpu", "memory", "io"):
    with open(os.path.join(_d, _k + ".pressure"), "w") as f:
        f.write("some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
os.environ["LANDER_LOADAVG"] = os.path.join(_d, "loadavg")
os.environ["LANDER_PSI_DIR"] = _d
