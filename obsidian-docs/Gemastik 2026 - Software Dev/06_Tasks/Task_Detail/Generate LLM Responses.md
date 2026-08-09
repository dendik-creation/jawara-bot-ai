# Generate LLM Responses

## Status

Done

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-10

## Description

Wire the documented JAWARA system prompt (persona, output rules, 4-part response structure) into the LLM call, assembling retrieved fact context / URL risk verdict, classification category, and risk level into the prompt. Enforce the 4-section output structure in code as a validation layer.

## Background

Converts verification-engine output (text RAG match or URL risk verdict) into the final empathetic, elder-friendly WhatsApp response defined in [[01_LLM_System_Prompt]].

## Deliverables

- System prompt loaded exactly as documented (no paraphrasing/drift)
- Prompt assembler injecting: user input, retrieved KB context or URL verdict, classification category, risk level
- Output formatter/validator checking the 4-section contract (status indicator, explanation, reference, forwardable draft) before dispatch

## Dependencies

- [[Build Text Verification Pipeline]]
- [[Integrate Safe Browsing]]
- [[Integrate VirusTotal]]

## Acceptance Criteria

- Output always contains exactly the 4 documented sections
- Forwardable draft section always begins every line with `>`
- Re-running the 5 documented few-shot inputs stays consistent with the documented examples in tone and structure
- Malformed LLM output (missing a section) is caught before dispatch, not sent to the user broken

## Related Documentation

- [[01_LLM_System_Prompt]]
- [[02_Data_Pipeline]]

## Notes

LLM provider is undecided in the vault — [[03_Tech_Stack]] lists "OpenAI GPT-4o-mini / Claude 3.5 Haiku" with no selection criteria ([[01_Documentation_Audit_Report]], finding #2). Resolve this before starting — pick one explicitly rather than building against both ambiguously. LLM-timeout static fallback template is a resilience feature, not required for the Sprint 1 milestone — defer unless time allows.

## Implementation (2026-08-08)

Keputusan provider diambil: **Anthropic Claude Haiku** (`claude-haiku-4-5-20251001`), dengan `openai` diimplementasikan penuh sebagai pembanding. Alasan pemilihan: [[Generate_LLM_Responses]] §1.

- `ml-service/prompts/system_prompt.txt` — salinan verbatim dari [[01_LLM_System_Prompt]]; ada test yang mem-parse dokumen vault dan gagal bila keduanya berbeda.
- `ml-service/app/llm/prompt.py` — perakit prompt; konteks knowledge disisipkan sebagai **data** dengan instruksi eksplisit untuk tidak mematuhinya ([[06_Platform_Security_Requirements]] §3).
- `ml-service/app/llm/validator.py` — validasi 4 bagian sebelum dispatch; pelanggaran kontrak = tolak, masalah gaya = peringatan.
- `ml-service/app/llm/template_provider.py` — komposer deterministik: default tanpa API key, sekaligus jalur perbaikan saat output LLM melanggar kontrak.

`ANTHROPIC_API_KEY` masih kosong di environment ini, jadi generasi yang benar-benar berjalan adalah komposer template. Detailnya: [[Generate_LLM_Responses]] §2.
