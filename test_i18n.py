"""Run: python3 test_i18n.py  (stdlib only)

The interface text is i18n.py's: four complete languages with matching placeholders, every key the SwiftUI app asks
for exists, no translation sits unused, and the Swift file generated from it is current."""
import os
import re
import string
import subprocess
import sys

import i18n

here = os.path.dirname(os.path.abspath(__file__))
en = i18n.STRINGS["en"]
assert set(i18n.LANGUAGES) == set(i18n.STRINGS) == {"en", "th", "zh", "fr"}
fmt = string.Formatter()
for lang, table in i18n.STRINGS.items():
    assert set(table) == set(en), (lang, set(en) ^ set(table))
    for key, text in table.items():
        assert text.strip(), (lang, key)
        want = {f for _, f, _, _ in fmt.parse(en[key]) if f}
        got = {f for _, f, _, _ in fmt.parse(text) if f}
        assert want == got, (lang, key, want, got)  # a translation must not lose or invent a {placeholder}
    assert table["advanced_btn"] != en["advanced_btn"] or lang == "en"  # not just a copy of the English
assert i18n.tr("fr", "done", n=3) == "Terminé. 3 fichier(s) enregistré(s)."
assert i18n.tr("xx", "ready") == "Ready"  # unknown language: English
print("i18n ok")

# the Swift sources: every key they ask for exists, and every translation is used (a few keys are built from a prefix)
src_dir = os.path.join(here, "app", "Sources", "MacImageEnhancer")
swift = "".join(open(os.path.join(src_dir, f)).read() for f in sorted(os.listdir(src_dir))
                if f.endswith(".swift") and not f.endswith(".generated.swift"))
literals = set(re.findall(r'"([a-z][a-z0-9_]*)"', swift))
asked = set(re.findall(r'\bt\("([a-z][a-z0-9_]*)"', swift))
assert len(asked) > 40, f"found only {len(asked)} text keys in calls: the scan no longer reads the Swift code properly"
assert asked <= set(en), f"the Swift code asks for text that does not exist: {asked - set(en)}"
built = {k for k in en if k.startswith(("unit_", "model_", "proc_"))}  # "unit_" + raw value, and so on
unused = set(en) - literals - built
assert not unused, f"translations the Swift code never uses: {sorted(unused)}"
print(f"all {len(asked)} text keys the app asks for exist, and every translation is used")

# the generated Swift files agree with i18n.py and enhance.plan_print
r = subprocess.run([sys.executable, os.path.join(here, "packaging", "gen_swift.py"), "--check"], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
print(r.stdout.strip())
print("ok")
