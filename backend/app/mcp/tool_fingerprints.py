# ruff: noqa: E501 -- public SHA-256 fingerprints carry explicit secret-scan annotations

EXPECTED_TOOL_FINGERPRINTS = {
    "context.get": "2e2b3cd3c0ca9ec67657ad8b2953dfd84c31454d1f0645c2216f9a24005a7bf5",  # pragma: allowlist secret
    "ops.list_failures": (
        "7a557c1fd6602406bf776272aeff6382833c8a6e768c82dc14907490ef60dbee"  # pragma: allowlist secret
    ),
    "tax.process_received_reports": (
        "cd1bf0660631bba901893e654253a231b813b85edcb23424c16341fde8c99b47"  # pragma: allowlist secret
    ),
    "parties.search": "eaa06912c1ed4ce7bda1086bb3e18ff1eb526e27203d1e3bff928fdac0b357c7",  # pragma: allowlist secret
    "parties.create": "66912fd439261d0c521dcb397e05ea74dfc3bd8b9d764585a9acf8568c36f92a",  # pragma: allowlist secret
    "products.search": "4f101518151a3528dc23dffc726605b5bd8f37317907ce6ff32bebc89c27bd87",  # pragma: allowlist secret
    "products.create": "7e98be20f8696a1ddd48c5335e9775e2c03a5b4f8e94aa7c9425c1584f295680",  # pragma: allowlist secret
    "leads.list": "345a04185847cf12dd155ab698e46a8f94538da9620429d1eabd3b38143ab170",  # pragma: allowlist secret
    "leads.activities": "43b07b77d43711cb5032d4e254390c3e1bd5de3cbb4d8f54661ef8a25d6faa63",  # pragma: allowlist secret
    "leads.create_with_party": (
        "e5e460e9a3250fb95c8a309e09efbfd52a6d0c8dbdaf0580dd9bb68a0cab218c"  # pragma: allowlist secret
    ),
    "leads.create_activity": (
        "bc7655270855e0c1b4444d5c11eb5a3bc9b1a7c41520e095a87f093b3eeb7ef8"  # pragma: allowlist secret
    ),
    "invoices.get": "ebfe2c0855f000ce67b3b032edaaf105f996ea62708e4bf725d736151de3ab93",  # pragma: allowlist secret
    "invoices.create_draft": (
        "f3bb8223f68e2cb147a392963a71c5ff24c8a1308a4ed5b158e8ec33ea26c69a"  # pragma: allowlist secret
    ),
    "invoices.issue": "be890a3144a1697f0060411347128d938047382c3ae9fb66c435716c0817f2a7",  # pragma: allowlist secret
    "credit_notes.create_and_issue": (
        "5262d81451539c1d2c323df3ad2349de60b68c56e683a09f1a8338e8b3ec3dd0"  # pragma: allowlist secret
    ),
    "receivables.list": (
        "fe5b1196696d09e7bc6e2e492ac07df084b3a63ad99a9074acbdab98f36db924"  # pragma: allowlist secret
    ),
    "receivables.record_payment": (
        "2edbcefd1d277d96e81214cfb39ec0ddb1e46c07e601ec5816d49bffb0bbfd4a"  # pragma: allowlist secret
    ),
    "receivables.send_reminder": (
        "7e39f766623d5c0036563e89582d457d350996c9f028b045dfe76155e2f0d6f6"  # pragma: allowlist secret
    ),
    "payables.list": "3a8cbe25d75289f2e3af8fb9d32b22417bf4ead5f8f39ec0f9dcbc8030c23ba1",  # pragma: allowlist secret
    "payables.create": "c00038903e25d55e8dceac9aa76185c96a146366da853e671dc8b9bc49713d60",  # pragma: allowlist secret
    "payables.create_from_document": (
        "60bfa0cd7445562f1bf9581cda5e970ac3b2d8573f7863690774f380fd41c1c5"  # pragma: allowlist secret
    ),
    "payables.schedule_payment": (
        "30c2ea49b5a7d04b60f359fa277b2412773428fcf865e54c35ba4589c05413d9"  # pragma: allowlist secret
    ),
    "payables.record_payment": (
        "df32c627a25a716e827a2effcaab790944bec62888feec25c436b7c9cefdb2a6"  # pragma: allowlist secret
    ),
}
