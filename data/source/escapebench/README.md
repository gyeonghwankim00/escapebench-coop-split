# EscapeBench source snapshots

These are unmodified source data files used to construct the eight full-source cooperative instances.

- Repository: https://github.com/qiancheng0/EscapeBench
- Paper: Qian et al., *EscapeBench: Towards Advancing Creative Intelligence of Language Model Agents*, ACL 2025. https://aclanthology.org/2025.acl-long.39/
- Retrieved branch archive: `https://codeload.github.com/qiancheng0/EscapeBench/tar.gz/refs/heads/main`
- Retrieval date: 2026-11-09 (Asia/Seoul).
- Upstream commit hash was not resolved. Reproducibility is pinned to the included bytes and SHA-256 hashes in each generated `environment.json`.

Included easy variants: `game1-1`, `game1-2`, `game1-3`, `game2-1`, `game2-2`, `game2-4`, `game2-5`, `game3-2`, and their corresponding `reference/key_log_*.txt` files. All bytes are copied unchanged from the previously retrieved archive. The reference files list key actions and positions; they are not complete movement traces or clue dependency annotations.

The archive inventory is saved in `upstream_inventory.json`: 12 base games, each with easy/default/hard variants (36 YAML settings). Only eight easy settings have been converted here. Difficulty variants are not independent base games.

The retrieved archive did not contain a top-level LICENSE file. No new license is asserted for upstream data in this project.
