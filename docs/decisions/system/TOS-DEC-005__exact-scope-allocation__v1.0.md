---
id: TOS-DEC-005
record_uuid: d82d41a6-c130-497a-8ea0-bb147e5ff6f4
title: Exact Scope Allocation Decision v0.1
status: accepted
version: 1.0
date: 2026-08-09
created_at: 2026-08-09T02:57:42Z
authority: DECISION_RECORD_ONLY
base_commit: dfa46625ea4f33419db7473475929f2fbadada28
record_owner: docs-manager
technical_owner: chief-engineer/00
consumer_chats:
  - chief-engineer/00
  - engine/01
  - test-risk/04
scope:
  - TOS-PACK-20260806-001
  - crates/execution-core
creation_reason: On exact path için tekil teknik sahiplik, mevcut genel klasör sahipliğiyle çözülemez.
supersedes_in_part: Önceki çelişen veya belirsiz scope tahsisleri, yalnız bu belgedeki on exact path için.
requires_action: false
---

# Exact Scope Allocation Decision v0.1

## Karar

TOS-PACK-20260806-001 için aşağıdaki on exact path tekil olarak tahsis edilir:

| Teknik sahip | Exact paths |
|---|---|
| `chief-engineer/00` | `crates/execution-core/src/lib.rs`<br>`crates/execution-core/src/event.rs`<br>`crates/execution-core/src/order.rs`<br>`crates/execution-core/src/types.rs`<br>`crates/execution-core/src/risk.rs` |
| `engine/01` | `crates/execution-core/src/engine.rs`<br>`crates/execution-core/src/portfolio.rs` |
| `test-risk/04` | `crates/execution-core/tests/domain_contract.rs`<br>`crates/execution-core/tests/policy_contract.rs`<br>`crates/execution-core/tests/performance_contract.rs` |

## Bağlayıcı hükümler

1. Listelenen her path'in tek sahibi vardır; tahsisler arasında path çakışması yoktur.
2. `engine/01` ve `test-risk/04`, `chief-engineer/00` paths'lerini yalnız okur. Değişiklik gereksinimi `chief-engineer/00` üzerinden yönlendirilir.
3. Shared core contract ve ortak fixture kararlarının teknik sahibi yalnız `chief-engineer/00`'dır.
4. Bridge altyapısı ile `schemas/message.schema.json` bu kararın dışındadır; mevcut `codex-dev` sahipliği değişmez.
5. WP-03 bu pack'in üyesi değildir.
6. İlk teknik dilim yalnız fill/pozisyon/portföy muhasebesi, deterministik `reduce(state, event)` ve state hash ile sınırlıdır.
7. Bu karar yalnız tabloda listelenen on exact path içindir; `crates/execution-core/` altındaki diğer tüm yollar kapsam dışıdır.
8. Karar preparation-only'dir: pack'i aktifleştirmez, görev zarfı veya lane claim oluşturmaz ve kodlama, commit, deployment ya da trading yetkisi doğurmaz.

## Kanıt ve ilişki

- Taban commit: `dfa46625ea4f33419db7473475929f2fbadada28`.
- Kayıt öncesinde `HEAD` bu commit'teydi; çalışma ağacı ve Git index temizdi.
- Önceki çelişen veya belirsiz scope tahsisleri silinmez veya yerinde değiştirilmez. Bu karar, yalnız yukarıdaki on path bakımından onların yerine geçer.
- Bu kayıt, kullanıcı onaylı Exact Scope Allocation Decision v0.1'in değişmez karar kaydıdır.
