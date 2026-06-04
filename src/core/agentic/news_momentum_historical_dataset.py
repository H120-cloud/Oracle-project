"""
Historical sample dataset of known news catalyst events for backtesting.
Each entry: ticker, headline, date (YYYY-MM-DD), known outcome category.
"""

HISTORICAL_EVENTS = [
    # ── FDA Approvals ── strong continuation expected ──
    {"ticker": "MRNA", "headline": "Moderna receives FDA approval for COVID-19 vaccine", "date": "2020-12-18", "expected": "continuation"},
    {"ticker": "BIIB", "headline": "FDA approves Biogen Alzheimer's drug Aduhelm", "date": "2021-06-07", "expected": "continuation"},
    {"ticker": "SRPT", "headline": "Sarepta Therapeutics announces FDA approval for gene therapy", "date": "2023-06-22", "expected": "continuation"},
    {"ticker": "KRTX", "headline": "Karuna Therapeutics receives FDA approval for schizophrenia treatment", "date": "2023-09-26", "expected": "continuation"},
    {"ticker": "AXSM", "headline": "Axsome Therapeutics receives FDA approval for depression drug Auvelity", "date": "2022-08-19", "expected": "continuation"},
    {"ticker": "PTCT", "headline": "PTC Therapeutics gets FDA clearance for Duchenne gene therapy", "date": "2023-06-22", "expected": "continuation"},
    {"ticker": "MORF", "headline": "MorphoSys receives FDA approval for blood cancer treatment Monjuvi", "date": "2020-08-03", "expected": "continuation"},
    {"ticker": "MRUS", "headline": "Merus announces FDA approval for bispecific antibody", "date": "2024-12-20", "expected": "continuation"},
    {"ticker": "ARWR", "headline": "Arrowhead Pharmaceuticals receives fast track designation for RNAi therapy", "date": "2023-11-15", "expected": "continuation"},
    {"ticker": "IONS", "headline": "Ionis Pharmaceuticals granted FDA approval for spinal muscular atrophy treatment", "date": "2020-04-28", "expected": "continuation"},

    # ── Phase Data / Clinical ──
    {"ticker": "APLS", "headline": "Apellis reports positive Phase 3 topline data for geographic atrophy", "date": "2022-09-08", "expected": "continuation"},
    {"ticker": "MRTX", "headline": "Mirati Therapeutics announces positive topline data for KRAS inhibitor", "date": "2022-12-12", "expected": "continuation"},
    {"ticker": "VKTX", "headline": "Viking Therapeutics reports positive Phase 2 data for NASH treatment", "date": "2024-02-27", "expected": "continuation"},
    {"ticker": "ARDX", "headline": "Ardelyx reports positive Phase 3 results for tenapanor in kidney disease", "date": "2021-03-31", "expected": "continuation"},
    {"ticker": "TPTX", "headline": "Turning Point Therapeutics announces positive Phase 1 data for lung cancer", "date": "2021-01-11", "expected": "continuation"},
    {"ticker": "DAWN", "headline": "Day One Biopharmaceuticals reports Phase 2 data for pediatric cancer therapy", "date": "2023-06-05", "expected": "continuation"},
    {"ticker": "VNDA", "headline": "Vanda Pharmaceuticals announces breakthrough therapy designation for Fanconi anemia", "date": "2024-09-16", "expected": "continuation"},
    {"ticker": "ACAD", "headline": "Acadia Pharmaceuticals reports positive topline data for Rett syndrome treatment", "date": "2023-03-06", "expected": "continuation"},

    # ── AI / Tech Partnerships ──
    {"ticker": "SOUN", "headline": "SoundHound AI announces partnership with Nvidia for voice AI platform", "date": "2024-02-29", "expected": "continuation"},
    {"ticker": "PLTR", "headline": "Palantir secures 480 million dollar Army AI contract", "date": "2024-03-05", "expected": "continuation"},
    {"ticker": "AI", "headline": "C3.ai announces AI partnership with Amazon Web Services", "date": "2023-06-22", "expected": "continuation"},
    {"ticker": "SMCI", "headline": "Super Micro Computer expands AI server infrastructure agreement", "date": "2024-01-18", "expected": "continuation"},
    {"ticker": "APP", "headline": "AppLovin announces AI-powered advertising platform partnership with major gaming studio", "date": "2024-05-14", "expected": "continuation"},
    {"ticker": "RGTI", "headline": "Rigetti Computing announces quantum computing partnership with Microsoft Azure", "date": "2023-12-12", "expected": "continuation"},
    {"ticker": "BBAI", "headline": "BigBear.ai secures multimillion dollar AI defense contract", "date": "2023-09-12", "expected": "continuation"},
    {"ticker": "LUNR", "headline": "Intuitive Machines announces lunar data processing contract with NASA", "date": "2024-02-22", "expected": "continuation"},
    {"ticker": "CRWV", "headline": "CoreWeave secures hyperscale GPU cloud contract with Meta", "date": "2024-06-18", "expected": "continuation"},
    {"ticker": "IREN", "headline": "Iris Energy announces AI data center infrastructure agreement", "date": "2024-03-20", "expected": "continuation"},

    # ── Earnings Beats / Guidance Raise ──
    {"ticker": "NVDA", "headline": "Nvidia beats earnings estimates raises guidance on AI demand surge", "date": "2023-05-24", "expected": "continuation"},
    {"ticker": "AMD", "headline": "AMD beats Q4 earnings raises full-year guidance on data center growth", "date": "2024-01-30", "expected": "continuation"},
    {"ticker": "NFLX", "headline": "Netflix subscriber growth beats expectations raises revenue guidance", "date": "2023-04-18", "expected": "continuation"},
    {"ticker": "AVGO", "headline": "Broadcom beats earnings raises dividend after VMware integration", "date": "2024-03-07", "expected": "continuation"},
    {"ticker": "DDOG", "headline": "Datadog beats Q3 earnings raises full year guidance on cloud monitoring demand", "date": "2023-11-07", "expected": "continuation"},
    {"ticker": "SNOW", "headline": "Snowflake beats revenue estimates raises product revenue guidance", "date": "2023-05-24", "expected": "continuation"},
    {"ticker": "CRM", "headline": "Salesforce beats Q4 earnings raises fiscal year guidance", "date": "2024-02-28", "expected": "continuation"},
    {"ticker": "ZS", "headline": "Zscaler beats earnings raises guidance on zero trust security adoption", "date": "2023-05-26", "expected": "continuation"},
    {"ticker": "FTNT", "headline": "Fortinet beats Q2 earnings raises billings guidance", "date": "2023-08-03", "expected": "continuation"},
    {"ticker": "PANW", "headline": "Palo Alto Networks beats earnings raises full year guidance on cybersecurity demand", "date": "2023-11-14", "expected": "continuation"},

    # ── M&A / Buyouts / Acquisitions ──
    {"ticker": "FITB", "headline": "Fitbit to be acquired by Google for 2.1 billion dollars", "date": "2019-11-01", "expected": "continuation"},
    {"ticker": "VMW", "headline": "Broadcom completes 69 billion dollar acquisition of VMware", "date": "2023-11-22", "expected": "continuation"},
    {"ticker": "HZNP", "headline": "Horizon Therapeutics to be acquired by Amgen for 27.8 billion dollars", "date": "2022-12-12", "expected": "continuation"},
    {"ticker": "ATVI", "headline": "Microsoft completes acquisition of Activision Blizzard", "date": "2023-10-13", "expected": "continuation"},
    {"ticker": "MXL", "headline": "MaxLinear to acquire Silicon Motion for 3.8 billion dollars", "date": "2022-05-05", "expected": "continuation"},
    {"ticker": "CTXS", "headline": "Citrix to be acquired by Vista Equity Partners and Elliott Investment Management", "date": "2022-01-31", "expected": "continuation"},
    {"ticker": "TDOC", "headline": "Teladoc Health announces strategic acquisition of chronic care platform", "date": "2021-04-14", "expected": "continuation"},
    {"ticker": "FSLR", "headline": "First Solar announces acquisition of European thin-film technology company", "date": "2023-08-08", "expected": "continuation"},

    # ── Negative: Offerings ── fade expected ──
    {"ticker": "XELA", "headline": "Exela Technologies announces 50 million dollar common stock offering", "date": "2021-03-15", "expected": "fade"},
    {"ticker": "GME", "headline": "GameStop announces equity offering program", "date": "2024-06-07", "expected": "fade"},
    {"ticker": "AMC", "headline": "AMC Entertainment files to sell up to 11 million shares of common stock", "date": "2021-06-03", "expected": "fade"},
    {"ticker": "BBBY", "headline": "Bed Bath and Beyond announces public offering of common stock", "date": "2022-08-31", "expected": "fade"},
    {"ticker": "LCID", "headline": "Lucid Group announces 3 billion dollar at-the-market offering program", "date": "2023-05-09", "expected": "fade"},
    {"ticker": "HOOD", "headline": "Robinhood announces equity offering to raise capital", "date": "2021-08-05", "expected": "fade"},
    {"ticker": "SOFI", "headline": "SoFi Technologies files for registered direct offering", "date": "2021-05-28", "expected": "fade"},
    {"ticker": "RBLX", "headline": "Roblox announces secondary offering by selling shareholders", "date": "2021-11-16", "expected": "fade"},
    {"ticker": "PLUG", "headline": "Plug Power announces 1 billion dollar common stock offering", "date": "2021-01-15", "expected": "fade"},

    # ── Negative: Reverse Split / Delisting ──
    {"ticker": "DBGI", "headline": "Digital Brands Group announces reverse stock split", "date": "2023-05-15", "expected": "fade"},
    {"ticker": "NIO", "headline": "NIO receives non-compliance notice from NYSE", "date": "2024-03-14", "expected": "fade"},
    {"ticker": "TSLA", "headline": "Tesla announces reverse stock split three-for-one", "date": "2022-08-05", "expected": "fade"},
    {"ticker": "AAL", "headline": "American Airlines receives delisting warning from Nasdaq", "date": "2020-05-15", "expected": "fade"},

    # ── Negative: Warrant Exercise / Toxic Financing ──
    {"ticker": "ASTI", "headline": "Ascent Solar Technologies announces warrant exercise and redemption", "date": "2024-01-18", "expected": "fade"},
    {"ticker": "MNMD", "headline": "MindMed announces convertible note financing", "date": "2023-07-20", "expected": "fade"},

    # ── Vague PR ── no-follow-through expected ──
    {"ticker": "SPCE", "headline": "Virgin Galactic provides business update on space tourism operations", "date": "2023-10-05", "expected": "no_follow_through"},
    {"ticker": "TELL", "headline": "Tellurian provides operational update on Driftwood LNG project", "date": "2023-08-15", "expected": "no_follow_through"},
    {"ticker": "WKHS", "headline": "Workhorse provides corporate update on delivery vehicle program", "date": "2023-09-08", "expected": "no_follow_through"},
    {"ticker": "CLOV", "headline": "Clover Health provides strategic update on Medicare Advantage growth", "date": "2023-11-02", "expected": "no_follow_through"},
    {"ticker": "OPEN", "headline": "Opendoor provides business update on home transaction volume", "date": "2023-08-24", "expected": "no_follow_through"},
    {"ticker": "CHPT", "headline": "ChargePoint provides update on EV charging station deployment", "date": "2023-09-27", "expected": "no_follow_through"},

    # ── Crypto / Bitcoin Treasury ──
    {"ticker": "MSTR", "headline": "MicroStrategy announces purchase of additional bitcoin for treasury", "date": "2024-03-11", "expected": "continuation"},
    {"ticker": "RIOT", "headline": "Riot Platforms expands bitcoin mining capacity with new facility", "date": "2024-01-24", "expected": "continuation"},
    {"ticker": "MARA", "headline": "Marathon Digital announces strategic bitcoin acquisition", "date": "2024-02-28", "expected": "continuation"},
    {"ticker": "COIN", "headline": "Coinbase announces institutional crypto custody expansion", "date": "2024-01-16", "expected": "continuation"},
    {"ticker": "HUT", "headline": "Hut 8 Mining announces merger with US Bitcoin Corp", "date": "2023-02-07", "expected": "continuation"},
    {"ticker": "CORZ", "headline": "Core Scientific announces bitcoin mining facility expansion agreement", "date": "2024-03-28", "expected": "continuation"},

    # ── Patent / Licensing / Strategic ──
    {"ticker": "VZ", "headline": "Verizon wins patent dispute case secures 1.5 billion dollars in damages", "date": "2023-12-15", "expected": "continuation"},
    {"ticker": "QCOM", "headline": "Qualcomm announces licensing agreement with major smartphone manufacturer", "date": "2023-11-08", "expected": "continuation"},
    {"ticker": "CRIS", "headline": "Crispr Therapeutics announces patent win in gene editing dispute", "date": "2022-02-28", "expected": "continuation"},
    {"ticker": "EDIT", "headline": "Editas Medicine secures licensing agreement for CRISPR technology", "date": "2023-06-14", "expected": "continuation"},
    {"ticker": "UPST", "headline": "Upstart announces partnership with major regional bank for AI lending", "date": "2023-07-18", "expected": "continuation"},
    {"ticker": "SQ", "headline": "Block announces strategic partnership with major retailer for payment processing", "date": "2023-10-10", "expected": "continuation"},

    # ── Biotech FDA Failures / Negative Data ── TRAP events ──
    {"ticker": "SRNE", "headline": "Sorrento Therapeutics announces FDA rejects emergency use authorization for COVID test", "date": "2021-08-20", "expected": "fade"},
    {"ticker": "NBIX", "headline": "Neurocrine Biosciences reports negative Phase 3 data for movement disorder", "date": "2023-05-22", "expected": "fade"},
    {"ticker": "ALNY", "headline": "Alnylam reports disappointing interim data for cardiovascular program", "date": "2022-11-14", "expected": "fade"},

    # ── Insider Buying ──
    {"ticker": "META", "headline": "Meta CEO Mark Zuckerberg purchases 50 million dollars of company stock", "date": "2022-10-27", "expected": "continuation"},
    {"ticker": "TSLA", "headline": "Tesla CEO Elon Musk exercises stock options and purchases additional shares", "date": "2022-04-26", "expected": "continuation"},

    # ── Debt Restructuring ──
    {"ticker": "DELL", "headline": "Dell Technologies announces debt refinancing and extension of credit facility maturity", "date": "2023-04-05", "expected": "continuation"},
    {"ticker": "CHPT", "headline": "ChargePoint announces debt restructuring agreement with lenders", "date": "2024-02-15", "expected": "continuation"},

    # ── Strategic Review / Sale Process ──
    {"ticker": "JCP", "headline": "JCPenney announces strategic review and explores sale of company", "date": "2020-05-15", "expected": "continuation"},
    {"ticker": "BBBY", "headline": "Bed Bath and Beyond announces strategic alternatives review", "date": "2022-09-15", "expected": "continuation"},

    # ── Profitability Inflection ──
    {"ticker": "DDOG", "headline": "Datadog announces first profitable quarter on record revenue growth", "date": "2021-02-11", "expected": "continuation"},
    {"ticker": "SNOW", "headline": "Snowflake reports first positive operating cash flow quarter", "date": "2022-02-24", "expected": "continuation"},
]
