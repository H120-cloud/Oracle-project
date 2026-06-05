"""
News Momentum Catalyst Classifier (V22)

Classifies headlines into catalyst categories and sub-types using
regex keyword matching. Extends the existing news_impact_engine
catalyst classification with more granular types.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

from src.core.agentic.news_momentum_models import CatalystCategory, CatalystSubType

logger = logging.getLogger(__name__)


# ── Keyword Maps ─────────────────────────────────────────────────────────────

BIOTECH_KEYWORDS = {
    CatalystSubType.FDA_APPROVAL: [
        r"fda approval", r"fda approves", r"approved by fda", r"regulatory approval",
        r"received approval", r"granted approval",
    ],
    CatalystSubType.FDA_CLEARANCE: [
        r"fda clearance", r"fda clears", r"cleared by fda", r"510\(k\) clearance",
        r"de novo clearance",
    ],
    CatalystSubType.PDUFA: [
        r"pdufa", r"pdufa date", r"fda action date",
    ],
    CatalystSubType.PHASE_1: [
        r"phase 1", r"phase i", r"first-in-human", r"initiate phase 1",
    ],
    CatalystSubType.PHASE_2: [
        r"phase 2", r"phase ii", r"initiate phase 2", r"begin phase 2",
    ],
    CatalystSubType.PHASE_3: [
        r"phase 3", r"phase iii", r"pivotal trial", r"initiate phase 3",
    ],
    CatalystSubType.FAST_TRACK: [
        r"fast track", r"fast-track",
    ],
    CatalystSubType.BREAKTHROUGH_THERAPY: [
        r"breakthrough therapy", r"breakthrough designation",
    ],
    CatalystSubType.ORPHAN_DRUG: [
        r"orphan drug", r"orphan designation",
    ],
    CatalystSubType.TOPLINE_DATA: [
        r"topline data", r"top-line data", r"topline results", r"interim data",
        r"positive data", r"clinical data", r"efficacy data",
    ],
    CatalystSubType.SNDA_SUBMISSION: [
        r"snda (filing|submission|acceptance)", r"supplemental new drug application",
        r"files snda", r"submits snda",
    ],
    CatalystSubType.NDA_APPROVAL: [
        r"nda (approval|approved|accepted)", r"new drug application.*(approved|accepted)",
        r"files nda", r"submits nda",
    ],
    CatalystSubType.LABEL_EXPANSION: [
        r"label expansion", r"expanded indication", r"new indication.*(fda|approval)",
        r"additional indication", r"broader label",
    ],
    CatalystSubType.DRUG_LAUNCH: [
        r"drug launch", r"product launch", r"commercial launch", r"market launch",
        r"rolls out.*(drug|therapy|treatment)", r"launches.*(drug|therapy|product)",
    ],
    CatalystSubType.COMMERCIALIZATION: [
        r"commercialization", r"commercialization agreement", r"enters commercial phase",
        r"first commercial sale", r"commercial milestone",
    ],
}

AI_TECH_KEYWORDS = {
    CatalystSubType.AI_PARTNERSHIP: [
        r"ai partnership", r"artificial intelligence partnership", r"ai collaboration",
        r"ai agreement", r"machine learning partnership",
        r"ai[- ]powered (partnership|agreement|deal|collaboration)",
        r"ai infrastructure (deal|agreement|partnership|division|push)",
        r"deploys? \d+,?\d* gpus?", r"\d+,?\d* gpus? deployed",
        r"ai cloud (provider|partnership|infrastructure)",
        r"high[- ]performance computing (partnership|agreement|deal)",
        # Quantum computing initiatives — major share-price mover
        r"quantum (computing|computer|processor) (initiative|partnership|deal|breakthrough|launch|announce|enter|expansion)",
        r"(enters?|expand(s|ing)?|announces?|launches?) (the )?quantum (computing|technology|space|market)",
        r"quantum (chip|hardware|software) (announce|partnership|breakthrough)",
        # Space / lunar / moon-based initiatives — these are huge multi-bagger catalysts
        r"(lunar|moon[- ]based) (initiative|manufacturing|computing|operations|program)",
        r"space[- ]based (manufacturing|computing|semiconductor|infrastructure|operations)",
        r"in[- ]space manufacturing", r"orbital manufacturing",
        r"strategic (lunar|space|moon) (initiative|push|expansion)",
        # Semiconductor manufacturing announcements (US chip act era is rocket fuel)
        r"semiconductor (fab|foundry|manufacturing) (announce|launch|build|open)",
        r"chip (fab|foundry|manufacturing) (announce|launch|build|open)",
        r"(announces?|launches?|approves?).*semiconductor (manufacturing|production|facility|fab)",
    ],
    CatalystSubType.NVIDIA_PARTNERSHIP: [
        # Require partnership/deal/agreement context — not just any nvidia mention
        r"nvidia partnership", r"nvidia collaboration", r"nvidia agreement",
        r"partnership with nvidia", r"collaboration with nvidia", r"deal with nvidia",
        r"nvidia[- ]powered", r"selected by nvidia", r"nvidia (selects|chooses|picks)",
        r"nvidia (inception|partner program)",
    ],
    CatalystSubType.OPENAI_PARTNERSHIP: [
        r"openai partnership", r"openai collaboration", r"openai agreement",
        r"partnership with openai", r"deal with openai",
        r"chatgpt integration", r"chatgpt partnership",
    ],
    CatalystSubType.HYPERSCALER_CONTRACT: [
        r"aws contract", r"amazon web services contract", r"azure contract", r"microsoft azure deal",
        r"google cloud contract", r"gcp contract", r"hyperscaler",
        r"(aws|azure|gcp) (deal|agreement|partnership)",
    ],
    CatalystSubType.INFRASTRUCTURE_AGREEMENT: [
        r"infrastructure agreement", r"data center (deal|agreement|contract)",
        r"compute agreement", r"cloud infrastructure (deal|agreement)",
    ],
    CatalystSubType.NEW_PRODUCT_LAUNCH: [
        r"new product launch", r"launches new product", r"product debut",
        r"unveils.*product", r"introduces.*platform", r"platform launch",
        r"rolls out.*(platform|service|solution)", r"new offering",
    ],
    CatalystSubType.PRODUCT_UPGRADE: [
        r"product upgrade", r"next generation", r"new version", r"major upgrade",
        r"enhanced.*(platform|product|service)", r"upgraded.*offering",
    ],
    CatalystSubType.PLATFORM_EXPANSION: [
        r"platform expansion", r"expands platform", r"extends platform",
        r"new capabilities", r"added features", r"platform enhancement",
    ],
    CatalystSubType.NEW_MARKET_ENTRY: [
        r"enters.*market", r"expands into.*market", r"new market.*entry",
        r"launches in.*(market|region|country)", r"international expansion",
    ],
}

FINANCIAL_KEYWORDS = {
    CatalystSubType.EARNINGS_BEAT: [
        r"earnings beat", r"beats earnings", r"beat estimates", r"exceeds expectations",
        r"revenue beat", r"profit beat", r"strong quarter",
        r"sales growth", r"revenue growth", r"double digit.*growth", r"double-digit.*growth",
        r"sales.*up.*\d+%", r"revenue.*up.*\d+%", r"growth.*accelerat",
        r"q\d+ sales.*\d+%", r"q\d+ revenue.*\d+%",
        r"strong.*sales", r"strong.*revenue", r"record.*(sales|revenue)",
        r"quarterly.*(sales|revenue).*growth",
    ],
    CatalystSubType.GUIDANCE_RAISE: [
        r"raises guidance", r"guidance raise", r"increases outlook", r"raises outlook",
        r"strong guidance", r"upbeat guidance",
        # "raises full-year guidance", "raises fy guidance", "raises q4 guidance"
        # — qualifier words between "raises" and "guidance" need a permissive gap
        r"raises (full[- ]year|fy|q[1-4]|annual|fiscal)? ?guidance",
        r"(raises|raise|raised|hiked|upped) (its )?(full[- ]year|fy|q[1-4]|annual|fiscal) (revenue |earnings |eps |sales )?(outlook|guidance|forecast)",
        r"reaffirms.*(raised|increased) guidance",
    ],
    CatalystSubType.PROFITABILITY_INFLECTION: [
        r"first profitable", r"turns profitable", r"profitability", r"positive ebitda",
        r"breakeven", r"first net income",
    ],
    CatalystSubType.DEBT_RESTRUCTURING: [
        r"debt restructuring", r"debt refinance", r"extends maturity", r"credit agreement",
        r"waives covenant",
        r"cut[s]? \$?\d+(\.\d+)?[mb] debt", r"reduce[s]? \$?\d+(\.\d+)?[mb] debt",
        r"trim[s]? \$?\d+(\.\d+)?[mb] debt", r"debt reduction",
        r"restructuring plan.*(approved|backed|support)",
    ],
    CatalystSubType.INSIDER_BUYING: [
        r"insider buying", r"insider purchase", r"ceo buys", r"director purchase",
        r"form 4", r"beneficial ownership",
    ],
    CatalystSubType.DIVIDEND_INCREASE: [
        r"dividend increase", r"raises dividend", r"increases dividend",
        r"dividend hike", r"special dividend", r"quarterly dividend increase",
    ],
    CatalystSubType.STOCK_SPLIT_FORWARD: [
        r"stock split", r"forward stock split", r"2-for-1", r"3-for-1",
        r"splits.*stock", r"board approves.*split",
    ],
    CatalystSubType.CREDIT_UPGRADE: [
        r"credit upgrade", r"credit rating upgrade", r"upgraded.*credit",
        r"s&p upgrade", r"moody's upgrade", r"fitch upgrade",
    ],
    CatalystSubType.FINANCING_POSITIVE: [
        r"credit facility", r"revolving credit", r"term loan",
        r"commitment increase", r"funding round", r"series [a-e] funding",
        r"venture capital", r"private placement", r"strategic investment",
        r"\bdip financing\b", r"debtor[- ]in[- ]possession financing",
        r"bridge financing", r"bridge funds", r"secure[s]? \$?\d+(\.\d+)?[mb] financing",
        r"lender[s]? .*back", r"lender[s]? .*support",
    ],
    CatalystSubType.DEBT_DOWNGRADE: [
        r"credit downgrade", r"credit rating downgrade", r"downgraded.*credit",
        r"s&p downgrade", r"moody's downgrade", r"fitch downgrade",
        r"junk status", r"below investment grade",
    ],
}

CRYPTO_KEYWORDS = {
    CatalystSubType.BITCOIN_TREASURY: [
        r"bitcoin treasury", r"btc treasury", r"holds bitcoin", r"crypto treasury",
        r"digital asset treasury",
        # Broader crypto holdings / allocation language
        r"allocates? (to|into) (bitcoin|btc|ethereum|eth|binance|bnb|solana|sol|crypto|digital asset)",
        r"allocates? \$?\d+.*(million|billion|m|b)?.*into (bitcoin|btc|ethereum|eth|binance|bnb|solana|sol|crypto|digital asset)",
        r"deploys? \$?\d+.*(million|billion)?.*into (bitcoin|btc|ethereum|eth|binance|bnb|solana|sol|crypto)",
        r"invests? \$?\d+.*(million|billion)?.*in (bitcoin|btc|ethereum|eth|binance|bnb|solana|sol|crypto)",
        r"strategic (position|allocation|investment) in (bitcoin|btc|ethereum|eth|binance|bnb|solana|sol|crypto|digital asset)",
        r"(crypto|digital asset|blockchain) (strategy|initiative|program|plan)",
        r"holdings? (of|in) (bitcoin|btc|ethereum|eth|binance|bnb|solana|sol|crypto)",
        r"acquires? (bitcoin|btc|ethereum|eth|binance|bnb|solana|sol|crypto)",
        r"purchases? (bitcoin|btc|ethereum|eth|binance|bnb|solana|sol|crypto)",
        # MSTR-style: "Bitcoin Purchase" / "BTC Purchase" / "holds over X BTC"
        r"(bitcoin|btc|ethereum|eth|solana|sol) purchase",
        r"\$?\d+\s*(million|billion)?\s*(bitcoin|btc) purchase",
        r"holds over \d+,?\d*\s*(bitcoin|btc|eth|ethereum|sol|solana)",
        r"now holds.*(bitcoin|btc|ethereum|eth|solana|sol)",
        r"adds? \d+,?\d*\s*(bitcoin|btc|ethereum|eth|solana|sol)",
        # Direct crypto mentions in treasury context
        r"binance coin", r"bnb (token|position|treasury|holding)",
        r"ethereum (position|treasury|holding)", r"eth (position|treasury|holding)",
        r"solana (position|treasury|holding)", r"sol (position|treasury|holding)",
    ],
    CatalystSubType.CRYPTO_MINING: [
        r"crypto mining", r"bitcoin mining", r"mining operation", r"mining facility",
        r"mining rig", r"hash rate", r"mining farm",
    ],
    CatalystSubType.BLOCKCHAIN_PARTNERSHIP: [
        r"blockchain partnership", r"blockchain agreement", r"web3 partnership",
        r"blockchain integration", r"web3 collaboration", r"decentralized finance", r"defi partnership",
    ],
    CatalystSubType.EV_BATTERY: [
        r"ev battery", r"electric vehicle battery", r"battery cell",
        r"lithium-ion battery", r"solid state battery", r"battery technology",
        r"battery manufacturing", r"gigafactory", r"battery supply",
    ],
    CatalystSubType.RENEWABLE_ENERGY: [
        r"renewable energy", r"solar energy", r"wind energy", r"hydrogen fuel",
        r"green hydrogen", r"clean energy", r"carbon neutral",
        r"net zero", r"esg initiative",
    ],
    CatalystSubType.CARBON_CREDIT: [
        r"carbon credit", r"carbon offset", r"carbon trading",
        r"emissions trading", r"carbon capture",
    ],
}

CORPORATE_KEYWORDS = {
    CatalystSubType.MERGER: [
        r"merger", r"merges with", r"merger agreement", r"combination with",
        # "Strategic combination creates" — common M&A press-release phrasing
        r"strategic combination", r"business combination",
        r"share[- ]for[- ]share exchange", r"all[- ]stock share exchange",
        r"share exchange",
    ],
    CatalystSubType.ACQUISITION: [
        r"acquisition", r"acquires", r"to acquire", r"acquired by", r"buyout",
        r"takeover", r"strategic acquisition",
        # Target-side / deal-structure phrasings that were previously missed
        r"to be acquired", r"agrees? to be acquired", r"acquired in",
        r"wholly owned (unit|subsidiary)",
        r"all[- ]cash (transaction|deal|merger|acquisition|offer)",
        r"definitive (merger |acquisition )?agreement",
        r"agrees? to acquire", r"enters? into.*(merger|acquisition) agreement",
    ],
    CatalystSubType.BUYOUT: [
        r"buyout", r"going[- ]private", r"acquisition proposal", r"take private",
        r"offer to acquire", r"\d+% premium to (last close|market price|closing price)",
        r"premium to (last close|market price|closing price)",
    ],
    CatalystSubType.STRATEGIC_REVIEW: [
        r"strategic review", r"explores alternatives", r"strategic alternatives",
        r"engages advisor", r"sale process",
        r"strategic reset", r"strategic update",
        r"strategic initiative", r"strategic plan",
        r"business transformation", r"operational turnaround",
    ],
    CatalystSubType.LICENSING_AGREEMENT: [
        r"licensing agreement", r"license deal", r"exclusive license",
        r"partnership agreement", r"collaboration agreement",
    ],
    CatalystSubType.PATENT_APPROVAL: [
        r"patent approval", r"patent granted", r"patent win", r"intellectual property",
        r"patent portfolio",
    ],
    CatalystSubType.GOVERNMENT_CONTRACT: [
        # NASA / defense / military / government contracts
        r"nasa contract", r"nasa (deal|agreement|award)", r"contract with nasa",
        r"defense contract", r"department of defense", r"\bdod (contract|award|deal)",
        r"pentagon contract", r"military contract", r"navy contract", r"army contract",
        r"air force contract", r"space force contract",
        r"government contract", r"federal contract", r"national security (contract|deal|launch)",
        r"\bgsa (contract|award)", r"\bdoe contract",  # General Services Admin / Dept of Energy
        r"\$?\d+\s*(million|billion|m|b)\s*(government|defense|federal|military|navy|army|air force) contract",
        r"awarded \$?\d+\s*(million|billion|m|b)?.*(contract|agreement)",
        r"wins? \$?\d+\s*(million|billion|m|b)\s*(contract|deal|award)",
        r"receives? \$?\d+\s*(million|billion|m|b)\s*(contract|deal|award)",
        r"secures? \$?\d+\s*(million|billion|m|b)\s*(contract|deal|award)",
        # "Navy selects ... for shipbuilding", "NASA selects ... for lunar mission"
        # — agency "selects" phrasing is extremely common but was missing
        r"(navy|army|air force|space force|nasa|pentagon|dod|nsa) (selects?|chooses?|picks?|awards?)",
        r"(selects?|chosen|awarded) (by|for).*(navy|army|air force|nasa|pentagon|dod)",
        r"\bnasa\b.*(payload|mission|launch|contract|award)",
    ],
    CatalystSubType.MAJOR_PARTNERSHIP: [
        # Tier-1 partner names — partnerships with major companies
        r"partnership with (apple|microsoft|google|amazon|meta|nvidia|tesla|samsung|sony|oracle|salesforce|ibm|cisco)",
        r"partnership with (at&t|verizon|t[- ]mobile|sprint|comcast|charter)",
        r"partnership with (walmart|target|costco|home depot|lowe.s|kroger|amazon|cvs|walgreens)",
        r"partnership with (boeing|lockheed|raytheon|northrop|general dynamics|spacex)",
        r"partnership with (jpmorgan|goldman sachs|morgan stanley|bank of america|wells fargo|citigroup)",
        r"partnership with (pfizer|merck|johnson & johnson|j&j|astrazeneca|novartis|roche|sanofi|gilead|moderna|novo nordisk)",
        r"partnership with (toyota|ford|gm|general motors|stellantis|volkswagen|bmw|mercedes|honda|hyundai)",
        r"strategic partnership with major",
        # Extended distribution agreements — add tech megacaps + pharma majors
        r"distribution agreement with (walmart|target|costco|home depot|lowe.s|kroger|amazon|cvs|walgreens)",
        r"distribution agreement with (apple|microsoft|google|samsung|sony|tesla|nvidia|meta|oracle|salesforce|ibm)",
        # Co-development / co-promotion — common pharma deal structures, were missed
        r"co[- ]development agreement with",
        r"co[- ]promotion agreement with",
        r"co[- ]marketing agreement with",
        # Strategic alliance with named majors
        r"strategic alliance with (apple|microsoft|google|amazon|meta|nvidia|tesla|samsung)",
        r"strategic alliance with (pfizer|merck|johnson & johnson|j&j|astrazeneca|novartis|roche|sanofi|gilead|moderna|novo nordisk)",
        r"(clinical supply|clinical trial collaboration and supply) agreement with (novo nordisk|pfizer|merck|johnson & johnson|j&j|astrazeneca|novartis|roche|sanofi|gilead|moderna)",
        # Direct-to-cell, In-vehicle, etc — flagship deals
        r"direct[- ]to[- ]cell", r"in[- ]vehicle (voice|ai|partnership|integration)",
        # Auto/tech major partnership
        r"partnership with major (auto|automotive|car) manufacturer",
        r"strategic partnership with major (german|japanese|korean|american|european) automaker",
        r"fortune 500 (partnership|company partnership|deal)",
        r"(lands?|landing|inks?|signs?|secures?) (a )?(deal|agreement|partnership|collaboration) with (a )?(global|major|leading|tier[- ]1|fortune 500)",
        r"(global|major|leading|tier[- ]1|fortune 500).*(electronics|technology|semiconductor|display|consumer electronics).*(deal|agreement|partnership|collaboration|customer)",
        r"paid proof[- ]of[- ]concept (agreement|deal|project|program)",
        r"proof[- ]of[- ]concept (agreement|deal|project|program) with (a )?(global|major|leading|tier[- ]1)",
    ],
    CatalystSubType.SUPPLY_AGREEMENT: [
        # Energy / utility / industrial supply deals
        r"\d+\s*(gw|mw|kwh|mwh) (supply|module|contract|agreement)",
        r"supply agreement (with|for)",
        r"clinical supply agreement",
        r"clinical trial collaboration and supply agreement",
        r"supply agreement with (novo nordisk|pfizer|merck|johnson & johnson|j&j|astrazeneca|novartis|roche|sanofi|gilead|moderna)",
        r"(wegovy|semaglutide).*(supply|clinical trial|phase 2b|phase ii)",
        r"solar module supply", r"battery supply", r"chip supply",
        r"long[- ]term supply", r"multi[- ]year supply",
        r"offtake agreement", r"power purchase agreement", r"\bppa\b.*(signed|executed|announced)",
        r"european utility (supply|agreement)", r"utility (supply agreement|contract)",
        r"\$?\d+\s*(million|billion)?\s*supply (deal|agreement|contract)",
    ],
    CatalystSubType.OEM_PARTNERSHIP: [
        # Auto OEM and similar industrial partnerships
        r"automaker (partnership|deal|agreement)", r"(german|japanese|korean) automaker",
        r"oem (partnership|deal|agreement)", r"with major oem",
        r"solid[- ]state batter(y|ies) (partnership|deal|agreement)",
        r"ev (oem|maker) (partnership|deal)",
        # Tier-1 supplier deals
        r"tier[- ]1 (supplier|partner)", r"flagship customer",
    ],
    CatalystSubType.SHARE_BUYBACK: [
        r"share (repurchase|buyback|buy-back) (program|plan|authorization|announcement)",
        r"(repurchase|buyback|buy-back).*(up to|\$)\d+.*(million|billion|m|b|shares)",
        r"(board )?approves.*(share repurchase|buyback|buy-back)",
        r"(share repurchase|buyback|buy-back).*(authorized|approved|announces)",
        r"\$\d+.*(million|billion).*share (repurchase|buyback)",
        r"class a.*share.*(repurchase|buyback)",
        r"(repurchase|buyback).*(common stock|class a|ordinary shares)",
        r"increases.*(share repurchase|buyback).*authorization",
    ],
    CatalystSubType.SPIN_OFF: [
        r"spin[- ]off", r"spinoff", r"spins off", r"to be spun off",
        r"divestiture", r"divests.*(unit|division|business)",
    ],
    CatalystSubType.JOINT_VENTURE: [
        r"joint venture", r"joint-venture", r"forms joint venture",
        r"jv agreement", r"jv partnership",
    ],
    CatalystSubType.MANAGEMENT_CHANGE_POSITIVE: [
        r"new ceo", r"new cfo", r"new cto", r"new president",
        r"appoints.*ceo", r"appoints.*cfo", r"appoints.*cto",
        r"names.*ceo", r"names.*cfo", r"hires.*executive",
        r"industry veteran.*(ceo|cfo|cto|president)",
        r"former.*(apple|google|amazon|microsoft|tesla).*joins",
    ],
    CatalystSubType.ANALYST_UPGRADE: [
        r"analyst upgrade", r"upgraded.*(buy|overweight|outperform)",
        r"raised.*(price target|pt)", r"raise.*(price target|pt)",
        r"overweight.*initiation", r"initiat.*overweight",
        r"buy.*initiation", r"strong buy",
        r"maintains.*buy.*rating", r"maintains.*overweight", r"maintains.*outperform",
        r"flash report.*buy", r"flash report.*overweight",
        r"price target.*\$\d+.*(from|raised|upped|hiked)",
        r"raises.*(price target|pt|target)",
        r"pt raised.*\$\d+", r"target.*raised.*\$\d+",
    ],
    CatalystSubType.TARIFF_EXEMPTION: [
        r"tariff exemption", r"tariff relief", r"exempt.*tariff",
        r"trade exemption", r"customs exemption",
    ],
    CatalystSubType.TRADE_DEAL: [
        r"trade deal", r"trade agreement", r"bilateral trade",
        r"free trade agreement", r"trade pact",
    ],
    CatalystSubType.SUBSIDY_AWARD: [
        r"subsidy", r"government subsidy", r"grant.*award",
        r"incentive.*program", r"tax credit.*award",
        r"receives.*\$?\d+.*(million|billion).*grant",
    ],
    CatalystSubType.WARRANT_OVERHANG_REMOVAL: [
        r"cashless warrant", r"full exercise of.*warrant", r"warrant redemption",
        r"zero exercise price", r"warrant overhang removal",
        r"exercise of.*warrant.*cashless", r"cancel.*outstanding warrant",
        r"warrant.*cancel", r"warrant.*expire.*unexercised",
    ],
    CatalystSubType.LISTING_COMPLIANCE: [
        r"regains compliance", r"regain compliance",
        r"compliance with.*nasdaq", r"nasdaq.*compliance",
        r"minimum bid price.*compliance", r"listing compliance",
        r"delisting.*averted", r"averted delisting",
        r"nasdaq.*continue.*list", r"continue.*list.*nasdaq",
    ],
}

NEGATIVE_KEYWORDS = {
    CatalystSubType.OFFERING: [
        r"public offering", r"registered offering", r"follow-on offering",
        r"common stock offering", r"equity offering", r"secondary offering",
        r"mixed shelf offering", r"shelf registration", r"files.*offering",
        r"\$\d+.*(million|billion).*offering",
    ],
    CatalystSubType.ATM_FILING: [
        r"at the market", r"atm offering", r"sales agreement", r"equity distribution",
        r"atm program", r"at-the-market",
    ],
    CatalystSubType.WARRANT_EXERCISE: [
        r"warrant exercise", r"warrant redemption", r"warrant call",
    ],
    CatalystSubType.REVERSE_SPLIT: [
        r"reverse split", r"reverse stock split", r"consolidation of shares",
    ],
    CatalystSubType.DELISTING_NOTICE: [
        r"delisting", r"nasdaq notice", r"non-compliance", r"listing deficiency",
        r"bid price deficiency", r"nyse notice",
    ],
    CatalystSubType.TOXIC_FINANCING: [
        r"toxic financing", r"convertible note", r"death spiral", r"dilutive financing",
        r"toxic convertible", r"variable conversion", r"discounted conversion",
    ],
    CatalystSubType.VAGUE_PR: [
        r"announces update", r"provides update", r"business update",
        r"corporate update", r"strategic update", r"operational update",
        r"no material impact", r"letter to shareholders",
    ],
    # ── Biotech negative events ─────────────────────────────────────────
    CatalystSubType.OTHER: [
        r"complete response letter", r"fda crl", r"receives crl",
        r"patient death", r"fatalit(y|ies)", r"mortality", r"patient died",
        r"trial failure", r"futility analys(is|es)", r"discontinue(s|d).*trial",
        r"terminat(es|ed).*study", r"trial discontinue",
        r"delays? (pdufa|approval|commercialization|launch)",
        r"postpone(s|d) (approval|launch|timeline)",
        r"clinical hold", r"partial clinical hold",
    ],
    # ── Corporate / operational negatives ────────────────────────────────
    CatalystSubType.OTHER: [
        r"workforce reduction", r"layoff", r"job cut", r"reduce(s|d) (workforce|headcount)",
        r"bankruptcy", r"chapter 11", r"chapter 7", r"restructuring",
        r"going concern", r"liquidation",
        r"sec investigation", r"sec subpoena", r"wells notice", r"sec inquiry",
        r"lawsuit", r"litigation", r"class action", r"shareholder (suit|lawsuit)",
        r"restate(s|d) (financial|earnings|revenue)", r"accounting error", r"material weakness",
        r"ceo resigns", r"cfo resigns", r"executive departure", r"cto resigns",
        r"product recall", r"voluntary recall", r"safety recall",
        r"data breach", r"cyber(security)? incident", r"ransomware",
        r"downgrade(s|d)", r"cut(s|ting) (rating|price target)",
        r"short report", r"bearish report", r"hindenburg",
        r"suspension", r"trading suspension", r"cease and desist",
    ],
    CatalystSubType.INVESTIGATION: [
        r"doj investigation", r"doj probe", r"department of justice.*investigation",
        r"ftc investigation", r"federal investigation", r"criminal investigation",
        r"grand jury", r"indictment", r"charged with", r"fraud investigation",
        r"antitrust investigation", r"price fixing.*investigation",
    ],
    CatalystSubType.ACCOUNTING_IRREGULARITIES: [
        r"accounting irregularit(y|ies)", r"revenue recognition.*(issue|problem)",
        r"improper revenue", r"fraudulent.*(financial|accounting)",
        r"cooking.*books", r"misstate.*(financial|earnings|revenue)",
        r"internal controls.*(weakness|deficiency|material)",
    ],
    CatalystSubType.MARGIN_PRESSURE: [
        r"margin pressure", r"margin contraction", r"compressing margin",
        r"cost inflation", r"rising cost", r"input cost.*(rise|increase)",
        r"supply chain.*(pressure|disruption)", r"labor cost.*(rise|increase)",
    ],
    CatalystSubType.GUIDANCE_CUT: [
        r"cuts guidance", r"guidance cut", r"lowers outlook", r"reduces guidance",
        r"below guidance", r"misses guidance", r"weak guidance",
        r"guides below.*expectation", r"downbeat guidance",
    ],
    CatalystSubType.EARNINGS_MISS: [
        r"earnings miss", r"misses earnings", r"misses estimate",
        r"revenue miss", r"profit miss", r"weak quarter",
        r"disappointing.*(earnings|revenue|results)",
    ],
    CatalystSubType.DIVIDEND_CUT: [
        r"dividend cut", r"cuts dividend", r"reduces dividend",
        r"suspends dividend", r"eliminates dividend",
    ],
    CatalystSubType.ANALYST_DOWNGRADE: [
        r"analyst downgrade", r"downgraded.*(sell|underweight|underperform)",
        r"cut.*(price target|pt)", r"underweight.*initiation",
        r"sell.*initiation", r"downgrade.*(hold|neutral)",
    ],
    CatalystSubType.SHORT_SELLER_REPORT: [
        r"short seller", r"short-selling", r"short attack",
        r"bearish research", r"negative research.*report",
        r"citron research", r"muddy waters", r"spruce point",
        r"iceberg research", r"j capital",
    ],
    # ── Biotech negatives ────────────────────────────────────────────────────
    CatalystSubType.CLINICAL_HOLD: [
        r"clinical hold", r"partial clinical hold", r"fda places.*hold",
        r"suspends.*trial", r"hold on.*trial",
    ],
    CatalystSubType.TRIAL_FAILURE: [
        r"trial failure", r"failed.*trial", r"study failure",
        r"primary endpoint.*not met", r"misses primary endpoint",
        r"did not meet.*endpoint", r"negative.*topline",
    ],
    CatalystSubType.SAFETY_SIGNAL: [
        r"safety signal", r"safety concern", r"adverse reaction",
        r"serious adverse event", r"sae", r"drug-related.*death",
        r"toxicity concern", r"safety review",
    ],
    CatalystSubType.ADVERSE_EVENT: [
        r"adverse event", r"serious adverse event", r"sae",
        r"side effect", r"drug-induced", r"treatment-related.*death",
    ],
}

# ── Context-sensitive patterns ────────────────────────────────────────────
# Same words can be bullish or bearish depending on context.
# Format: (trigger_regex, bullish_context_regex, bearish_context_regex, default_category)
# If both match, bearish wins (conservative — false positives are costly).

CONTEXT_SENSITIVE_PATTERNS: List[Tuple[str, str, str, CatalystCategory]] = [
    # "rejects" + "offer/bid" = bearish (deal fell through)
    # "rejects" + "lawsuit/claim/allegation" = bullish (won the case)
    (r"\breject(s|ed|ing)\b", r"(lawsuit|claim|allegation|accusation|complaint)", r"(offer|bid|proposal|deal|merger|acquisition)", CatalystCategory.CORPORATE),

    # "delays" + "approval/launch" = bearish
    # "delays" + "offering/split" = neutral/positive (dilution delayed)
    (r"\bdelay(s|ed|ing)\b", r"(offering|split|reverse split)", r"(approval|launch|commercialization|timeline|pdufa)", CatalystCategory.CORPORATE),

    # "cuts" + "price target/rating" = bearish (analyst action against company)
    # "cuts" + "costs/prices" = bullish (margin expansion)
    (r"\bcut(s|ting)\b", r"(cost|expense|price for consumer|workforce|headcount|jobs)", r"(price target|pt|rating|guidance|dividend|forecast|outlook)", CatalystCategory.FINANCIAL),

    # "terminates" + "contract/deal" = bearish
    # "terminates" + "lawsuit/investigation" = bullish
    (r"\bterminat(e|es|ed|ing)\b", r"(lawsuit|investigation|probe|litigation|agreement.*dispute)", r"(contract|deal|partnership|agreement|relationship)", CatalystCategory.CORPORATE),

    # "withdraws" + "offering" = bullish (no dilution)
    # "withdraws" + "guidance/nda" = bearish
    (r"\bwithdraw(s|n|ed|ing)\b", r"(offering|atm|shelf|registration|filing)", r"(guidance|nda|application|filing.*approval)", CatalystCategory.CORPORATE),

    # "misses" + "earnings/revenue" = bearish
    (r"\bmiss(es|ed|ing)\b", r"", r"(earnings|revenue|profit|estimate|target|goal|guidance)", CatalystCategory.NEGATIVE),

    # "suspends" + "dividend/buyback" = bearish
    # "suspends" + "offering/atm" = bullish (no dilution)
    (r"\bsuspend(s|ed|ing)\b", r"(offering|atm|shelf|registration|ipo|filing)", r"(dividend|buyback|repurchase|guidance|outlook|operations|production)", CatalystCategory.CORPORATE),
]

ALL_CATEGORIES = {
    CatalystCategory.BIOTECH: BIOTECH_KEYWORDS,
    CatalystCategory.AI_TECH: AI_TECH_KEYWORDS,
    CatalystCategory.FINANCIAL: FINANCIAL_KEYWORDS,
    CatalystCategory.CRYPTO: CRYPTO_KEYWORDS,
    CatalystCategory.CORPORATE: CORPORATE_KEYWORDS,
    CatalystCategory.NEGATIVE: NEGATIVE_KEYWORDS,
}


# ── Subtype → Category mapping ────────────────────────────────────────────
SUBTYPE_TO_CATEGORY: dict[CatalystSubType, CatalystCategory] = {
    # Biotech
    CatalystSubType.FDA_APPROVAL: CatalystCategory.BIOTECH,
    CatalystSubType.FDA_CLEARANCE: CatalystCategory.BIOTECH,
    CatalystSubType.PHASE_1: CatalystCategory.BIOTECH,
    CatalystSubType.PHASE_2: CatalystCategory.BIOTECH,
    CatalystSubType.PHASE_3: CatalystCategory.BIOTECH,
    CatalystSubType.FAST_TRACK: CatalystCategory.BIOTECH,
    CatalystSubType.BREAKTHROUGH_THERAPY: CatalystCategory.BIOTECH,
    CatalystSubType.ORPHAN_DRUG: CatalystCategory.BIOTECH,
    CatalystSubType.PDUFA: CatalystCategory.BIOTECH,
    CatalystSubType.TOPLINE_DATA: CatalystCategory.BIOTECH,
    CatalystSubType.SNDA_SUBMISSION: CatalystCategory.BIOTECH,
    CatalystSubType.NDA_APPROVAL: CatalystCategory.BIOTECH,
    CatalystSubType.LABEL_EXPANSION: CatalystCategory.BIOTECH,
    CatalystSubType.DRUG_LAUNCH: CatalystCategory.BIOTECH,
    CatalystSubType.COMMERCIALIZATION: CatalystCategory.BIOTECH,
    CatalystSubType.CLINICAL_HOLD: CatalystCategory.NEGATIVE,
    CatalystSubType.TRIAL_FAILURE: CatalystCategory.NEGATIVE,
    CatalystSubType.SAFETY_SIGNAL: CatalystCategory.NEGATIVE,
    CatalystSubType.ADVERSE_EVENT: CatalystCategory.NEGATIVE,
    # AI/Tech
    CatalystSubType.AI_PARTNERSHIP: CatalystCategory.AI_TECH,
    CatalystSubType.NVIDIA_PARTNERSHIP: CatalystCategory.AI_TECH,
    CatalystSubType.OPENAI_PARTNERSHIP: CatalystCategory.AI_TECH,
    CatalystSubType.HYPERSCALER_CONTRACT: CatalystCategory.AI_TECH,
    CatalystSubType.INFRASTRUCTURE_AGREEMENT: CatalystCategory.AI_TECH,
    CatalystSubType.NEW_PRODUCT_LAUNCH: CatalystCategory.AI_TECH,
    CatalystSubType.PRODUCT_UPGRADE: CatalystCategory.AI_TECH,
    CatalystSubType.PLATFORM_EXPANSION: CatalystCategory.AI_TECH,
    CatalystSubType.NEW_MARKET_ENTRY: CatalystCategory.AI_TECH,
    # Financial
    CatalystSubType.EARNINGS_BEAT: CatalystCategory.FINANCIAL,
    CatalystSubType.GUIDANCE_RAISE: CatalystCategory.FINANCIAL,
    CatalystSubType.PROFITABILITY_INFLECTION: CatalystCategory.FINANCIAL,
    CatalystSubType.DEBT_RESTRUCTURING: CatalystCategory.FINANCIAL,
    CatalystSubType.INSIDER_BUYING: CatalystCategory.FINANCIAL,
    CatalystSubType.DIVIDEND_INCREASE: CatalystCategory.FINANCIAL,
    CatalystSubType.STOCK_SPLIT_FORWARD: CatalystCategory.FINANCIAL,
    CatalystSubType.CREDIT_UPGRADE: CatalystCategory.FINANCIAL,
    CatalystSubType.FINANCING_POSITIVE: CatalystCategory.FINANCIAL,
    CatalystSubType.DEBT_DOWNGRADE: CatalystCategory.NEGATIVE,
    CatalystSubType.GUIDANCE_CUT: CatalystCategory.NEGATIVE,
    CatalystSubType.EARNINGS_MISS: CatalystCategory.NEGATIVE,
    CatalystSubType.DIVIDEND_CUT: CatalystCategory.NEGATIVE,
    # Crypto
    CatalystSubType.BITCOIN_TREASURY: CatalystCategory.CRYPTO,
    CatalystSubType.CRYPTO_MINING: CatalystCategory.CRYPTO,
    CatalystSubType.BLOCKCHAIN_PARTNERSHIP: CatalystCategory.CRYPTO,
    CatalystSubType.EV_BATTERY: CatalystCategory.CRYPTO,
    CatalystSubType.RENEWABLE_ENERGY: CatalystCategory.CRYPTO,
    CatalystSubType.CARBON_CREDIT: CatalystCategory.CRYPTO,
    # Corporate
    CatalystSubType.MERGER: CatalystCategory.CORPORATE,
    CatalystSubType.ACQUISITION: CatalystCategory.CORPORATE,
    CatalystSubType.BUYOUT: CatalystCategory.CORPORATE,
    CatalystSubType.STRATEGIC_REVIEW: CatalystCategory.CORPORATE,
    CatalystSubType.LICENSING_AGREEMENT: CatalystCategory.CORPORATE,
    CatalystSubType.PATENT_APPROVAL: CatalystCategory.CORPORATE,
    CatalystSubType.GOVERNMENT_CONTRACT: CatalystCategory.CORPORATE,
    CatalystSubType.MAJOR_PARTNERSHIP: CatalystCategory.CORPORATE,
    CatalystSubType.SUPPLY_AGREEMENT: CatalystCategory.CORPORATE,
    CatalystSubType.OEM_PARTNERSHIP: CatalystCategory.CORPORATE,
    CatalystSubType.SHARE_BUYBACK: CatalystCategory.CORPORATE,
    CatalystSubType.SPIN_OFF: CatalystCategory.CORPORATE,
    CatalystSubType.JOINT_VENTURE: CatalystCategory.CORPORATE,
    CatalystSubType.MANAGEMENT_CHANGE_POSITIVE: CatalystCategory.CORPORATE,
    CatalystSubType.ANALYST_UPGRADE: CatalystCategory.CORPORATE,
    CatalystSubType.TARIFF_EXEMPTION: CatalystCategory.CORPORATE,
    CatalystSubType.TRADE_DEAL: CatalystCategory.CORPORATE,
    CatalystSubType.SUBSIDY_AWARD: CatalystCategory.CORPORATE,
    CatalystSubType.WARRANT_OVERHANG_REMOVAL: CatalystCategory.CORPORATE,
    CatalystSubType.LISTING_COMPLIANCE: CatalystCategory.CORPORATE,
    # Negative
    CatalystSubType.OFFERING: CatalystCategory.NEGATIVE,
    CatalystSubType.ATM_FILING: CatalystCategory.NEGATIVE,
    CatalystSubType.WARRANT_EXERCISE: CatalystCategory.NEGATIVE,
    CatalystSubType.REVERSE_SPLIT: CatalystCategory.NEGATIVE,
    CatalystSubType.DELISTING_NOTICE: CatalystCategory.NEGATIVE,
    CatalystSubType.TOXIC_FINANCING: CatalystCategory.NEGATIVE,
    CatalystSubType.VAGUE_PR: CatalystCategory.NEGATIVE,
    CatalystSubType.OTHER: CatalystCategory.NEGATIVE,
    CatalystSubType.INVESTIGATION: CatalystCategory.NEGATIVE,
    CatalystSubType.ACCOUNTING_IRREGULARITIES: CatalystCategory.NEGATIVE,
    CatalystSubType.MARGIN_PRESSURE: CatalystCategory.NEGATIVE,
    CatalystSubType.ANALYST_DOWNGRADE: CatalystCategory.NEGATIVE,
    CatalystSubType.SHORT_SELLER_REPORT: CatalystCategory.NEGATIVE,
}


def classify_headline(headline: str) -> tuple[CatalystCategory, CatalystSubType, bool, bool]:
    """
    Classify a headline into catalyst category and sub-type.

    Uses NLP semantic classifier first (trained on seed data + feedback),
    falls back to regex keyword matching if NLP confidence is low.

    Returns:
        (category, sub_type, is_negative, is_vague)
    """
    text = headline.lower()

    # ── Context-sensitive patterns (disambiguate ambiguous words) ───────────
    for trigger, bullish_ctx, bearish_ctx, default_cat in CONTEXT_SENSITIVE_PATTERNS:
        if re.search(trigger, text):
            has_bullish = bool(bullish_ctx) and re.search(bullish_ctx, text)
            has_bearish = bool(bearish_ctx) and re.search(bearish_ctx, text)
            if has_bearish:
                # Bearish context wins (conservative)
                logger.debug("Context-sensitive: bearish match for '%s...'", headline[:40])
                return CatalystCategory.NEGATIVE, CatalystSubType.OTHER, True, _is_vague(text)
            if has_bullish:
                logger.debug("Context-sensitive: bullish match for '%s...'", headline[:40])
                return default_cat, CatalystSubType.OTHER, False, _is_vague(text)

    # ── Negative sentinel: override NLP when strong negative words present ──
    # These patterns indicate clear negative events that the NLP classifier
    # (trained mostly on positive catalysts) often misclassifies.
    restructuring_language = bool(re.search(r"chapter 11|bankruptcy|restructuring", text))
    debt_relief_language = bool(re.search(
        r"cut[s]? .*debt|reduce[s]? .*debt|trim[s]? .*debt|debt reduction|"
        r"debt restructuring|restructuring plan",
        text,
    ))
    rescue_financing_language = bool(re.search(
        r"\bdip financing\b|debtor[- ]in[- ]possession financing|"
        r"bridge (financing|funds)|secure[s]? .*financing|lender[s]? .*back|"
        r"lender[s]? .*support|keep[s]? operations running|exit[s]? chapter 11",
        text,
    ))
    if restructuring_language and debt_relief_language and rescue_financing_language:
        logger.debug("Restructuring rescue matched for '%s...'", headline[:40])
        return CatalystCategory.FINANCIAL, CatalystSubType.DEBT_RESTRUCTURING, False, _is_vague(text)

    negative_sentinels = [
        (r"complete response letter|receives crl|fda crl", CatalystSubType.OTHER),
        (r"patient death|fatalit(y|ies)|mortality|patient died", CatalystSubType.OTHER),
        (r"trial failure|futilit(y|ies)|discontinue(s|d).*trial|terminat(es|ed).*trial", CatalystSubType.OTHER),
        (r"delays? (pdufa|approval|commercialization|launch|timeline)", CatalystSubType.OTHER),
        (r"workforce reduction|layoff|job cut|reduce(s|d) (workforce|headcount)", CatalystSubType.OTHER),
        (r"bankruptcy|chapter 11|restructuring|going concern|liquidation", CatalystSubType.OTHER),
        (r"sec investigation|sec subpoena|wells notice|sec inquiry", CatalystSubType.OTHER),
        (r"lawsuit|litigation|class action|shareholder (suit|lawsuit)", CatalystSubType.OTHER),
        (r"restate(s|d) (financial|earnings|revenue)|accounting error|material weakness", CatalystSubType.OTHER),
        (r"ceo resigns|cfo resigns|executive departure|cto resigns|chairman resigns", CatalystSubType.OTHER),
        (r"product recall|recall(s|ed)|safety recall|voluntary recall", CatalystSubType.OTHER),
        (r"data breach|cyber(security)? incident|hack(ed)?|ransomware", CatalystSubType.OTHER),
        (r"\bdowngrade(s|d)?\b|downgrad(ed|ing)|cut(s|ting) (rating|price target|estimate)", CatalystSubType.OTHER),
        (r"short report|bearish report|hindenburg|research report.*short", CatalystSubType.OTHER),
        (r"suspension|halt(s|ed)|trading suspension|cease and desist", CatalystSubType.OTHER),
        # Reverse split is a distress/dilution signal — must NOT be confused with
        # a bullish forward split (the FORWARD pattern r"stock split" otherwise
        # matches "reverse stock split" and the regex tie-break favors FINANCIAL).
        (r"reverse (stock )?split|consolidation of shares", CatalystSubType.REVERSE_SPLIT),
        # Trial failure phrasings — otherwise "Phase 2 trial failed" gets the
        # PHASE_2 biotech tag (because "phase 2" outscores generic neg keywords)
        # and slips through as BULLISH. Has to be a sentinel to win pre-regex.
        (r"trial (failed|did not meet|missed)|failed to meet (the )?primary (endpoint|outcome)|failed.*primary endpoint", CatalystSubType.TRIAL_FAILURE),
    ]
    for pattern, sub_type in negative_sentinels:
        if re.search(pattern, text):
            is_vague = _is_vague(text)
            logger.debug("Negative sentinel matched for '%s...' -> %s", headline[:40], sub_type)
            return CatalystCategory.NEGATIVE, sub_type, True, is_vague

    # ── NLP semantic classification (primary) ───────────────────────────
    # IMPORTANT: the default fallback below MUST be a real CatalystCategory member.
    # Previously this was CatalystCategory.OTHER which doesn't exist → AttributeError
    # on every call → caught silently → the entire NLP path was dead for any subtype
    # not in SUBTYPE_TO_CATEGORY. Same class of silent-death bug as the original
    # NLP enum issue. UNKNOWN is the right fallback (it exists, and downstream
    # treats it as "no recognised catalyst").
    try:
        from src.core.agentic.news_momentum_nlp_classifier import classify_headline as nlp_classify
        nlp_subtype, nlp_conf = nlp_classify(headline)
        if nlp_conf >= 0.55:
            # ── NLP REFINEMENT ────────────────────────────────────────────
            # The NLP model has only 14 coarse labels — it correctly identifies
            # a deal/event class but can't always pick the most specific subtype.
            # Run targeted regex post-checks on the headline to refine the NLP
            # bucket into a more precise subtype where one obviously applies.
            # Example: "Breakthrough therapy designation" → NLP says fda_approval
            # at 0.80; refinement promotes it to BREAKTHROUGH_THERAPY which is
            # what the gates and ML actually want to see.
            if nlp_subtype == CatalystSubType.FDA_APPROVAL:
                if re.search(r"breakthrough therapy|breakthrough designation", text):
                    nlp_subtype = CatalystSubType.BREAKTHROUGH_THERAPY
                elif re.search(r"orphan drug|orphan designation", text):
                    nlp_subtype = CatalystSubType.ORPHAN_DRUG
                elif re.search(r"fast[- ]track", text):
                    nlp_subtype = CatalystSubType.FAST_TRACK
                elif re.search(r"\bpdufa\b|fda action date", text):
                    nlp_subtype = CatalystSubType.PDUFA
                elif re.search(r"phase 3|phase iii|pivotal trial", text):
                    nlp_subtype = CatalystSubType.PHASE_3
                elif re.search(r"phase 2|phase ii", text):
                    nlp_subtype = CatalystSubType.PHASE_2
                elif re.search(r"phase 1|phase i\b|first-in-human", text):
                    nlp_subtype = CatalystSubType.PHASE_1
            elif nlp_subtype == CatalystSubType.OFFERING:
                # "ATM offering" / "at-the-market sales agreement" → ATM_FILING
                # (different gates / risk treatment than a standard offering)
                if re.search(r"\batm\b|at[- ]the[- ]market|equity distribution", text):
                    nlp_subtype = CatalystSubType.ATM_FILING
            elif nlp_subtype == CatalystSubType.ACQUISITION:
                if re.search(r"merger agreement|definitive merger|strategic combination|business combination|merges with", text):
                    nlp_subtype = CatalystSubType.MERGER
                elif re.search(r"going[- ]private|take private|premium to (last close|market price|closing price)|buyout", text):
                    nlp_subtype = CatalystSubType.BUYOUT
            elif nlp_subtype == CatalystSubType.SUPPLY_AGREEMENT:
                # NLP often confuses distribution-with-tier-1 with supply.
                # If a tier-1 name is present, it's really a MAJOR_PARTNERSHIP.
                tier1 = (
                    r"apple|microsoft|google|amazon|meta|nvidia|tesla|samsung|sony|oracle|"
                    r"salesforce|ibm|walmart|target|costco|home depot|kroger|cvs|walgreens|"
                    r"pfizer|merck|johnson & johnson|j&j|astrazeneca|novartis|roche|sanofi|gilead|moderna|novo nordisk|"
                    r"toyota|ford|gm|general motors|stellantis|volkswagen|bmw|mercedes|honda|hyundai|"
                    r"boeing|lockheed|raytheon|northrop|general dynamics|spacex"
                )
                if re.search(rf"\b({tier1})\b", text) and re.search(r"distribution|partnership|alliance|co[- ](dev|prom|market)", text):
                    nlp_subtype = CatalystSubType.MAJOR_PARTNERSHIP

            nlp_category = SUBTYPE_TO_CATEGORY.get(nlp_subtype, CatalystCategory.UNKNOWN)
            is_negative = nlp_category == CatalystCategory.NEGATIVE
            is_vague = _is_vague(text) or nlp_subtype == CatalystSubType.VAGUE_PR
            logger.debug("NLP classified '%s...' as %s (conf=%.2f)", headline[:40], nlp_subtype, nlp_conf)
            return nlp_category, nlp_subtype, is_negative, is_vague
    except Exception as exc:
        logger.debug("NLP classification failed for '%s...': %s", headline[:40], exc)

    # ── Regex keyword fallback ──────────────────────────────────────────
    category_scores: dict[CatalystCategory, int] = {}
    best_subtypes: dict[CatalystCategory, CatalystSubType] = {}

    for category, keyword_map in ALL_CATEGORIES.items():
        max_score = 0
        best_subtype = CatalystSubType.OTHER
        for sub_type, patterns in keyword_map.items():
            score = sum(1 for pat in patterns if re.search(pat, text))
            if score > max_score:
                max_score = score
                best_subtype = sub_type
        category_scores[category] = max_score
        best_subtypes[category] = best_subtype

    # Pick category with highest match score
    if category_scores:
        best_category = max(category_scores, key=category_scores.get)
        best_score = category_scores[best_category]
    else:
        best_category = CatalystCategory.UNKNOWN
        best_score = 0

    if best_score == 0:
        return CatalystCategory.UNKNOWN, CatalystSubType.OTHER, False, _is_vague(text)

    is_negative = best_category == CatalystCategory.NEGATIVE
    is_vague = _is_vague(text) or best_subtypes[best_category] == CatalystSubType.VAGUE_PR

    return best_category, best_subtypes[best_category], is_negative, is_vague


def _is_vague(text: str) -> bool:
    """Detect if a headline is vague / non-specific."""
    vague_phrases = [
        r"announces update",
        r"provides update",
        r"business update",
        r"corporate update",
        r"strategic update",
        r"operational update",
        r"no material impact",
        r"letter to shareholders",
        r"comments on",
        r"responds to",
        r"aware of",
        r"monitoring situation",
    ]
    return any(re.search(p, text) for p in vague_phrases)


def classify_headline_with_confidence(headline: str) -> dict:
    """Classify with detailed confidence info."""
    category, sub_type, is_negative, is_vague = classify_headline(headline)
    return {
        "category": category.value,
        "sub_type": sub_type.value,
        "is_negative": is_negative,
        "is_vague": is_vague,
    }
