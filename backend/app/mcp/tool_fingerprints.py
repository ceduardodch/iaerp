# ruff: noqa: E501 -- public SHA-256 fingerprints carry explicit secret-scan annotations

EXPECTED_TOOL_FINGERPRINTS = {
    "context.get": "268e7362ad3c30c68ba002ba840d721edad5b68136870906b154222a6fe2e2cc",  # pragma: allowlist secret
    "parties.search": "b30a69092abd26274feb8b60c1c7a80c0c1f105f2b7a35bd7d1c54f9412b396c",  # pragma: allowlist secret
    "parties.create": "f0695b4c27be49292b13d400ae64fb9b6a0480746029692824498b4f6dba1872",  # pragma: allowlist secret
    "products.search": "b640ea9c44a3f30f37dc5cde233dd1a05be2dfa8413b5b32c9e2cc85492c3403",  # pragma: allowlist secret
    "products.create": "bc421a47996e139fcfbd936dd535dd5e31cac0f4f6932e4c36acc3186b7f8667",  # pragma: allowlist secret
    "leads.list": "127bd0c4ab273a7f4d562dcabb3f243279a94d8380b9ad58e20ac6349f1956dc",  # pragma: allowlist secret
    "leads.activities": "dbcccf6a58861016ea0b51eab3650e18339d54e1aec5fc086db9ecef7bfe4f60",  # pragma: allowlist secret
    "leads.create_with_party": (
        "724c4a7a3b786691fbb8f9ac0ddbc6ef474d118ec41dd785b10b68bffa9720e0"  # pragma: allowlist secret
    ),
    "leads.create_activity": (
        "27eba68d532a173e1c0f22fb4d730653ecc1698025851c8f944578ff2b63a483"  # pragma: allowlist secret
    ),
    "invoices.get": "8ab5c5b6cf7c22ce2bdc1b1bcfb554b76b4aecc7ac17df181c05ef132652db25",  # pragma: allowlist secret
    "invoices.create_draft": (
        "143f994ca96d058274076052e60e54da306380efedd2d9fc8a5015082b3090ec"  # pragma: allowlist secret
    ),
    "invoices.issue": "503285bd8fa6e9e4a6f7c0847dcd904cc0f85926a8586e70c01421876633b4f3",  # pragma: allowlist secret
    "credit_notes.create_and_issue": (
        "da7c2af6c5d991fc7c843555f689bed90d6b90716ae2b4e089eb8ff2f743b24c"  # pragma: allowlist secret
    ),
    "receivables.list": (
        "873bdfdac2c03b4694afc15d36e1fc58c98039d3e8a3f8c4d43ad53c51866e5c"  # pragma: allowlist secret
    ),
    "receivables.record_payment": (
        "421b053528cda8f95c2139e73511db369b04109cda3e86c973baa6041c495d27"  # pragma: allowlist secret
    ),
    "receivables.send_reminder": (
        "7bf3c061c255df09f4ad70cafe2f7c586b8fe97941fe9f2680b425bbec29bbe4"  # pragma: allowlist secret
    ),
    "payables.list": "7a2bb13faaa5cc6344b8b923260936e053363ad8607939e0528e7fce37a430f4",  # pragma: allowlist secret
    "payables.create": "f0f79db2ffce051ae715b098d60e39a0f9fbbb2c793826ca04bec2975fec2fef",  # pragma: allowlist secret
    "payables.create_from_document": (
        "fb74b3320414a6e9af5c423e2ebd755227cb343328e41bfaad2ce7dff8358c98"  # pragma: allowlist secret
    ),
    "payables.schedule_payment": (
        "8d7c7a13656a69ead0923ee4851db4b5e50f774e9a554cb36b7b393da0d14281"  # pragma: allowlist secret
    ),
    "payables.record_payment": (
        "426eb6950084f3a97f279a0fb3652360c875bef12c3efab26ec70e88c0c7006f"  # pragma: allowlist secret
    ),
}
