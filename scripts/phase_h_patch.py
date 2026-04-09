import sys

SRC = "/root/x-posting-system/app/orchestrator.py"

with open(SRC) as f:
    L = f.readlines()

n = len(L)
print(f"Read {n} lines")

t = "".join(L)
if "_KO_ONLY_DOMAINS" in t:
    print("ABORT: already patched")
    sys.exit(1)

# --- P3: full_pipeline line 676 (bottom-up) ---
exp3 = "            sent = await self.send_for_approval(draft.id)\n"
if L[675] != exp3:
    print(f"ABORT P3: line 676 = {L[675]!r}")
    sys.exit(1)
L[675:676] = [
    "            # Phase H: KO-only routing - skip approval card\n",
    "            if getattr(draft, '_skip_approval_card', False):\n",
    "                sent = False\n",
    "                logger.info(f\"[pipeline] approval card skipped (KO-only): draft_id={draft.id}\")\n",
    "            else:\n",
    "                sent = await self.send_for_approval(draft.id)\n",
]
print("P3 OK: full_pipeline +5")

# --- P2: _handle_regenerate line 650 ---
exp2 = "            await self.send_for_approval(new_draft.id)\n"
if L[649] != exp2:
    print(f"ABORT P2: line 650 = {L[649]!r}")
    sys.exit(1)
L[649:650] = [
    "            # Phase H: KO-only routing - skip approval card\n",
    "            if not getattr(new_draft, '_skip_approval_card', False):\n",
    "                await self.send_for_approval(new_draft.id)\n",
]
print("P2 OK: regen +2")

# --- P1: Step 1.7 before line 221 ---
if "Step 2" not in L[220]:
    print(f"ABORT P1: line 221 = {L[220]!r}")
    sys.exit(1)

blk = [
    "\n",
    "        # Step 1.7: KO-only routing - skip English draft pipeline (Phase H, fail-open)\n",
    "        _KO_ONLY_DOMAINS = {\"\uae08\uc735\", \"\ud22c\uc790\", \"\ud06c\ub9bd\ud1a0\", \"\uc8fc\uc2dd\"}\n",
    "        _KO_ONLY_CLASSES = {\"BREAKING_NOW\", \"CANDIDATE\"}\n",
    "        try:\n",
    "            _br = getattr(source_item, \"breaking_result\", None)\n",
    "            if (_br is not None\n",
    "                    and _br.classification in _KO_ONLY_CLASSES\n",
    "                    and _br.topic_domain in _KO_ONLY_DOMAINS):\n",
    "                logger.info(\n",
    "                    f\"[1.7/6] English draft skipped: {_br.classification} \"\n",
    "                    f\"domain={_br.topic_domain}\"\n",
    "                )\n",
    "                draft = self.draft_service.create_draft(\n",
    "                    source_item=source_item,\n",
    "                    hook=f\"[{_br.classification}] {data.title[:80]}\",\n",
    "                    body=f\"KO-only pipeline (English draft skipped). domain={_br.topic_domain}\",\n",
    "                    category=ContentCategory.ECONOMY,\n",
    "                    risk_level=RiskLevel.LOW,\n",
    "                    risk_reasoning=f\"{_br.classification} KO-only routing\",\n",
    "                    ai_rationale=f\"Routed to {_br.classification} pipeline, English draft skipped.\",\n",
    "                )\n",
    "                draft._skip_approval_card = True\n",
    "                logger.info(\n",
    "                    f\"=== Pipeline done (KO-only): draft_id={draft.id}, \"\n",
    "                    f\"routing={_br.classification} ===\"\n",
    "                )\n",
    "                return draft\n",
    "        except Exception as e:\n",
    "            logger.warning(f\"[1.7] KO routing check failed (fail-open): {e}\")\n",
    "\n",
]
L[220:220] = blk
print(f"P1 OK: Step 1.7 +{len(blk)} lines")

with open(SRC, "w") as f:
    f.writelines(L)
print(f"DONE: {n} -> {len(L)} lines")
