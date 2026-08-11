# SMU_ALL — DV 品質流程狀態圖

- **IP**: `SMU_ALL` · **Milestone**: `P2`
- **Pin**: `hw/sys/smu/dv/tb/SMU_ALL_PIN.yaml`
- **最後更新**: 2026-08-05
- **目前狀態**: Skill 3 advisory **PASS** — 待 owner milestone Done
- **Board**: `hw/sys/smu/dv/tb/audit_status_smu_all.md`

## Standing order
owner：都審核過 → 簽署；繼續實作；不可 Force/deposit；推薦 B；candidate 自動核准；evidence-closed 自動 signoff。

## Progress
```
   [x] 001–008 Skill 2 PROVEN + SIGNOFF（r18 card hashes）
   [x] Skill 3 peer audit PASS (26/26)  — agent 09db09e7
   [!] Owner milestone Done  ◀━━ 現在在這裡
```

## Skill 3 summary
| 項 | 值 |
|---|---|
| Result | **PASS** |
| Required / Covered | **26 / 26** |
| Deferred P3 | 95 × OUT-OF-MILESTONE（不計分母） |
| reverse_diff | CLEAN |
| Report | `hw/sys/smu/dv/tb/SMU_ALL_PEER_AUDIT.md` |

## 下一 session 指令
```
Owner: reply "Done" / milestone signoff for SMU_ALL P2
(optional later) /dv_vplan_gen Continue SMU_ALL P3 for deferred keys
Board: hw/sys/smu/dv/tb/audit_status_smu_all.md
Peer: hw/sys/smu/dv/tb/SMU_ALL_PEER_AUDIT.md
```
