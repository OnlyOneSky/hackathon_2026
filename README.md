# 安全的 Agent 開發迴圈 — 參考實作

> 對應 2026 Cathay AI Hackathon 一頁題目：
> **「規格為靶、憲法為界 — 能自動寫碼、測試、修正直到達標的銀行開發 AI Agent 迴圈」**
>
> 這份參考實作展示題目所描述的受控 Actor↔Critic 迴圈：Codex 負責寫碼，
> 我們自己的確定性程式碼負責測試、憲法檢核、迭代上限與人工把關。

---

## 核心觀念（先讀這段）

「Loop engineering（迴圈設計）」不是寫一個很厲害的 prompt，也不是某種會自己運作的魔法。
**它就是一支由你撰寫的普通程式（一個 `for` 迴圈），在迴圈裡呼叫 AI 當作其中的步驟。**

- 「Agent」＝一次帶著特定 prompt 的模型呼叫（或一次 `codex exec`）。
- 是 **orchestrator（你的程式碼）** 決定：呼叫誰、用什麼順序、何時重跑、何時停止。
- 模型提供「智慧」；你的迴圈提供「控制、安全上限、與外部系統的接線」。

對銀行而言，真正有價值的正是 AI 呼叫**外圈**那些不起眼的控制與安全程式碼。

---

## 檔案總覽

| 檔案 | 角色 | 對應一頁題目的哪一塊 |
| --- | --- | --- |
| `orchestrator.py` | **主迴圈（Codex 混合版）**。Codex 當 Actor 寫碼，其餘關卡是我們的確定性程式碼。 | 「AI 輔助做法」整段 |
| `orchestrator_rawapi.py` | 同一個迴圈的純 API 版（模型回傳程式碼、由我們寫檔）。用來對照理解。 | 同上（教學對照用） |
| `constitution.md` | 版本控管、可維護的安全與合規規則集。對 Actor 唯讀。 | 「憲法為界」、可擴散的護欄 |
| `prompts/spec.txt` | Spec agent：把需求轉成可測試的驗收規格。 | 「規格為靶」 |
| `prompts/actor.txt` | Actor：實作功能；明訂不得修改測試與憲法。 | Actor（執行者） |
| `prompts/qa_critic.txt` | QA Critic：測試通過後，判斷驗收是否真正滿足。 | Critic（QA agent） |
| `prompts/security_critic.txt` | Security Critic：逐條對照憲法、唯讀、附證據。 | Critic（Security agent） |

---

## 迴圈如何運作：七個階段

對應 `orchestrator.py` 的 `run_loop()`：

1. **Spec**（`spec.txt`）— 需求 → 可測試的驗收規格 ＋ 適用的憲法條款。
2. **人工關卡 #1：審查規格**（`review_spec`）— 在寫任何程式碼之前，由人確認
   「規格是否對準業務真意」。核准 / 修改 / 退回三種結果。這是測試與 Critic 都無法
   代勞的一關（它們只能查「程式對不對規格」，不能查「規格對不對需求」）。
3. **Actor**（`codex exec`）— Codex 讀程式庫、直接在磁碟上改檔實作。
4. **強制檢核**（`assert_no_protected_changes`）— 用 `git diff` 確認 Actor 沒動到
   `tests/` 或 `constitution.md`；動了就 `git checkout` 還原並退回重跑。
5. **確定性測試關卡**（`run_tests`）— 由我們自己跑測試，Codex 不能自我認證。
6. **QA Critic**（`qa_critic.txt`）— 測試過了，再判斷邊界值、漏測等測試抓不到的問題。
7. **Security Critic**（`security_critic.txt`）— 唯讀，逐條對照憲法，附證據行號。
8. **人工關卡 #2：收斂或交回人工** — 全部通過 → 開 PR（**不自動合併**），交人工確認；
   或達到迭代/時間上限 → 安全停止並回報。

每一步都是「上一步的程式碼呼叫了它」而觸發 —— 沒有自動的 agent 間交接，沒有魔法。

---

## 防弊設計 ↔ 評分對應

| 風險 | 迴圈中的對應機制 | 主要對應評分面向 |
| --- | --- | --- |
| Reward hacking（偷改測試讓它過） | 測試＋憲法對 Actor 唯讀；事後 `git diff` 偵測並還原 | 可行性 |
| 無限迴圈 / 失控 | `MAX_ITERATIONS` ＋ `MAX_WALL_SECONDS`，達標即停 | 可行性 |
| LLM 主觀誤判 | 先確定性測試把關，再交 LLM 評審 | AI 工具應用程度 |
| 違反合規而不自知 | Security Critic 逐條對照可維護的憲法 | 可行性 / 業務價值 |
| 自動合併出錯 | 只開 PR，合併前一定人工確認 | 可行性 |
| 規則會變動 | 憲法是版本控管檔案，改一條即套用到後續所有變更，並可交他隊沿用 | 業務價值 / 擴散 |
| 建錯東西（規格誤解業務真意） | 人工關卡 #1 在寫碼前審查規格；自動關卡無法代勞此判斷 | 可行性 / 業務價值 |

---

## 為什麼用 Codex CLI（而非純 API）

- Codex 本身就是 agent，會自己讀檔、改檔、跑指令，所以「寫檔」這個接線從 Actor 步驟消失，
  迴圈更短。對應指令：`codex exec --sandbox workspace-write --json --skip-git-repo-check`。
- 但**安全關卡仍留在我們的程式碼裡、在 Codex 之外**——這正是整份題目的安全主張。
- 代價：對 Codex 回合內部可見度較低，所以「不得改測試」這條改為**事後**用 `git diff` 強制
  （偵測並還原），而非事前阻擋。同樣的保證，換個機制達成——而且這個「偵測並還原竄改」
  本身就是一個具體、可示範的反取巧控制。

---

## 落地前要做的事（建置順序）

1. 把 `constitution.md` 放進 repo（先從幾條最關鍵的規則開始，不必一次寫全）。
2. 個別驗證四個 prompt：手動丟一段需求給 Spec、丟一段規格給 Actor，確認各自輸出合理。
3. **逐一**測試每個 connector：`run_tests()` 真的能跑測試並讀回結果嗎？能開 PR 嗎？
   （在迴圈裡 debug 壞掉的 API 呼叫很痛苦，務必先單獨測。）
4. 設定憑證：`GITHUB_TOKEN`（讀碼、推分支、開 PR）、`OPENAI_API_KEY`（Codex）、
   `ANTHROPIC_API_KEY`（Spec／Critic 的模型呼叫）。
5. 先手動跑一次 `codex exec --json "小任務"`，看實際的最後一筆 JSON 事件長相，
   再依賴 `_last_json_line`。
6. 最後才把 orchestrator 接起來跑整個迴圈。迴圈是最後、也最簡單的部分——它只是膠水。

---

## 已知限制（誠實揭露）

- orchestrator 是**忠實的參考實作，非開箱即用**：部分小工具為示意版，Git 推送流程
  假設 `REPO_DIR` 是乾淨的本地 clone。
- `codex exec --json` 的事件 schema 會演進；接線時請以實測為準。
- 效益目前以質性描述為主（產出一個已審查、合規、測試通過的 PR）。若能在截止前實測
  一次單一功能的迴圈耗時，補上一個誠實的數字會明顯強化「業務價值」這一面向。
