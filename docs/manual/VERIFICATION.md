# Verification Log — eFloStop II Production Operator Manual

Deliverable: `docs/manual/eFloStop_II_Production_Operator_Manual.docx`
Built by: `docs/manual/build_manual.py` · Figures by: `docs/manual/capture/capture.py`
Manifest: `docs/manual/screenshot_manifest.md`

## Acceptance criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | `.docx` re-opens without repair | **PASS** — `python-docx` re-parsed the file; ZIP integrity OK; **every** XML part (`document.xml`, headers/footers, `settings.xml`, `[Content_Types].xml`, `.rels`) is well-formed (malformed parts = NONE — the usual cause of Word's repair prompt). |
| 2 | ToC present, points to real headings | **PASS** — a `TOC \o "1-3"` field is present, `w:updateFields` is set so Word builds it on open, and there are **57 Heading 1–3 targets**. |
| 3 | Flows A, B, C each a complete, numbered, operator-level procedure | **PASS** — Program/Test/QR are numbered step-by-step in Ch. 5 (Hub), 6 (Valve), 7 (Sensor); QR/app-linking consolidated in Ch. 8. |
| 4 | Every step references a real UI label (spot-check cited) | **PASS** — see the spot-check table below. |
| 5 | Every figure has a numbered caption + embedded image or a manifest-backed placeholder | **PASS** — 27 numbered figure captions; 26 embedded images (Fig 4 & 9 share the identical Hub-READY capture, deduped by python-docx); 6 placeholders, each listed in the manifest + Appendix B; **no inline figure reference lacks a caption**. |
| 6 | No feature/threshold/label/QR format without a code basis; hub QR accurate | **PASS** — content derived from the citation-backed discovery; only the live plain-text query-string QR is documented; the stale base64/JSON + ZPL/25 mm paths and the title-bar version are explicitly excluded (Appendix B.3). |
| 7 | Revision table on the cover page | **PASS** — document-control table + revision-history table on the cover. |

## Validation commands run

- `Document(path)` re-open → parsed OK.
- `zipfile.testzip()` → `None` (no corrupt entries).
- `lxml.etree.fromstring` over every `.xml`/`.rels` part → 0 malformed.
- `word/media/` image count → 26; footer `PAGE`/`NUMPAGES` fields present.
- Non-ASCII audit → only intended glyphs (—, “ ”, →, ⚠, ℹ, •, …, ✔, ✘, ≠).

> Note: no LibreOffice/Word-headless renderer is installed on this machine, so a pixel-level
> page render was not performed; correctness was validated structurally (schema-well-formed
> OOXML, valid relationships, valid ZIP) plus visual verification of every embedded PNG.

## Spot-check: manual claim → source citation

| Manual text | Source |
|-------------|--------|
| Tabs "WiFi Hub / Valve / Leak Sensor / History" | app/ui/main_window.py:86-89 |
| "Enter your Operator ID before starting." | app/ui/tab_wifi_hub.py:196-198 |
| Firmware strip green = all present / red = missing | app/ui/main_window.py:134-169; app/services/firmware_registry.py:43-52 |
| Banner READY / RUNNING… / PASS / FAIL | app/ui/widgets/big_status.py:13-34 |
| Step symbols pending/running/pass/fail/skipped | app/ui/widgets/step_list.py:10-16 |
| "Operator Check" dialog, YES/NO buttons | app/ui/widgets/question_dialog.py:29,56-74 |
| Hub "Serial Port:" / "No CP210x ports found" | app/ui/tab_wifi_hub.py:75-92,167-173 |
| Valve "UART Port (ST-Link VCP):" / "(Skip UART capture)" | app/ui/tab_valve.py:83-93,166-175 |
| Sensor "UART Port (Tag-Connect):" / "No serial ports found" | app/ui/tab_leak_sensor.py:74-84,156-162 |
| Servo prompt "Press the button on the valve. Did the servo actuate (valve moved)?" | app/ui/tab_valve.py:484-494 |
| Leak-probe prompt (LEAK DETECTED) | app/ui/tab_leak_sensor.py:384-394 |
| "Validate battery range (2.5-3.3V)" + 2.5–3.3 V threshold | app/devices/leak_sensor.py:66-68; app/workers/functional_test.py:184-190 |
| QR payload `id=<id>&type=<type>&hw=<hw>&sw=v<fw>` | app/services/qr_generator.py:47-59 |
| Prefixes GW- / VV- / LK- | app/services/qr_generator.py:18-22 |
| Serial prefixes EFS2H / EFS2V / EFS2S | app/config/settings.py:63-67 |
| 40 mm QR print via Print Label / Printer Setup | app/ui/widgets/qr_preview.py:101-118,141-200 |
| History 10 columns + Export CSV | app/ui/tab_history.py:79-82; app/services/record_logger.py:70-93 |
| Hub does NOT re-flash; Valve/Sensor re-flash production | app/ui/tab_wifi_hub.py (no `_flash_production`) vs app/ui/tab_valve.py:508-569; app/ui/tab_leak_sensor.py:399-468 |

## Placeholders remaining (6) — replace before release

Fig 3b (red firmware strip), Fig 10/14/19 (Hub/Valve wiring + coin-cell photos),
Fig 24 (printed 40 mm label photo), Fig 26 (Windows Printer Setup dialog). Each has a
reproduction recipe in **Appendix B.3**.

## Notes

- **Read-only against the tool:** no firmware or production-tool source file was modified.
  The capture harness imports the tool as a library and drives its own UI methods.
- **Not a git repository:** the "feature branch / no push" instruction could not apply;
  files were created under `docs/manual/` only.
- **No fixed version number** is printed in the manual body (per project preference); the
  operator types the batch version into "Expected FW version".
