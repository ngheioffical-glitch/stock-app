"""行業中文名：Yahoo 板塊／行業（Nasdaq 分類做後備）。對照唔到就顯示英文原名。"""

SECTOR_ZH = {
    # Yahoo
    "Technology": "科技", "Communication Services": "通訊服務", "Consumer Cyclical": "非必需消費",
    "Consumer Defensive": "必需消費", "Financial Services": "金融", "Healthcare": "醫療", "Industrials": "工業",
    "Energy": "能源", "Basic Materials": "原材料", "Real Estate": "地產", "Utilities": "公用事業",
    # Nasdaq
    "Finance": "金融", "Consumer Discretionary": "非必需消費", "Health Care": "醫療", "Consumer Staples": "必需消費",
    "Telecommunications": "通訊服務", "Miscellaneous": "其他",
}

INDUSTRY_ZH = {
    # 科技
    "Semiconductors": "半導體", "Semiconductor Equipment & Materials": "半導體設備",
    "Software - Infrastructure": "基建軟件", "Software - Application": "應用軟件", "Computer Hardware": "電腦硬件",
    "Communication Equipment": "通訊設備", "Consumer Electronics": "消費電子", "Electronic Components": "電子零件",
    "Scientific & Technical Instruments": "科學儀器", "Information Technology Services": "資訊科技服務",
    "Electronics & Computer Distribution": "電子分銷", "Solar": "太陽能",
    # 通訊服務
    "Internet Content & Information": "互聯網內容", "Entertainment": "娛樂", "Telecom Services": "電訊服務",
    "Advertising Agencies": "廣告", "Electronic Gaming & Multimedia": "電子遊戲", "Publishing": "出版",
    "Broadcasting": "廣播",
    # 消費
    "Internet Retail": "網上零售", "Auto Manufacturers": "汽車製造", "Auto Parts": "汽車零件",
    "Auto & Truck Dealerships": "汽車經銷", "Restaurants": "餐飲", "Specialty Retail": "專門零售",
    "Home Improvement Retail": "家居裝修零售", "Apparel Retail": "服裝零售", "Apparel Manufacturing": "服裝製造",
    "Footwear & Accessories": "鞋類及配飾", "Travel Services": "旅遊服務", "Lodging": "酒店",
    "Resorts & Casinos": "度假村及賭場", "Gambling": "博彩", "Leisure": "休閒", "Residential Construction": "住宅建築",
    "Packaging & Containers": "包裝", "Luxury Goods": "奢侈品", "Department Stores": "百貨公司",
    "Furnishings, Fixtures & Appliances": "家具及家電", "Personal Services": "個人服務", "Discount Stores": "折扣店",
    "Grocery Stores": "超市", "Beverages - Non-Alcoholic": "非酒精飲品", "Beverages - Brewers": "啤酒",
    "Beverages - Wineries & Distilleries": "酒類", "Confectioners": "糖果", "Packaged Foods": "包裝食品",
    "Farm Products": "農產品", "Household & Personal Products": "家居及個人用品", "Tobacco": "煙草",
    "Education & Training Services": "教育", "Food Distribution": "食品分銷",
    # 金融
    "Banks - Diversified": "綜合銀行", "Banks - Regional": "地區銀行", "Capital Markets": "資本市場",
    "Asset Management": "資產管理", "Credit Services": "信貸服務", "Insurance - Diversified": "綜合保險",
    "Insurance - Property & Casualty": "財產保險", "Insurance - Life": "人壽保險", "Insurance - Reinsurance": "再保險",
    "Insurance Brokers": "保險經紀", "Financial Data & Stock Exchanges": "金融數據及交易所",
    "Financial Conglomerates": "金融集團", "Mortgage Finance": "按揭融資", "Shell Companies": "空殼公司",
    # 醫療
    "Drug Manufacturers - General": "大型藥廠", "Drug Manufacturers - Specialty & Generic": "專科及仿製藥",
    "Biotechnology": "生物科技", "Medical Devices": "醫療器材", "Medical Instruments & Supplies": "醫療儀器及用品",
    "Diagnostics & Research": "診斷及研究", "Healthcare Plans": "醫療保險", "Medical Care Facilities": "醫療設施",
    "Medical Distribution": "醫療分銷", "Health Information Services": "醫療資訊服務", "Pharmaceutical Retailers": "藥房",
    # 工業
    "Aerospace & Defense": "航天及國防", "Specialty Industrial Machinery": "專用工業機械",
    "Farm & Heavy Construction Machinery": "農業及重型機械", "Electrical Equipment & Parts": "電氣設備",
    "Engineering & Construction": "工程及建造", "Building Products & Equipment": "建築材料及設備",
    "Industrial Distribution": "工業分銷", "Railroads": "鐵路", "Trucking": "貨車運輸", "Airlines": "航空",
    "Airports & Air Services": "機場服務", "Integrated Freight & Logistics": "物流", "Marine Shipping": "航運",
    "Waste Management": "廢物管理", "Rental & Leasing Services": "租賃服務", "Security & Protection Services": "保安服務",
    "Specialty Business Services": "專業商業服務", "Consulting Services": "顧問服務",
    "Staffing & Employment Services": "人力資源", "Conglomerates": "綜合企業", "Tools & Accessories": "工具",
    "Metal Fabrication": "金屬加工", "Pollution & Treatment Controls": "污染處理", "Infrastructure Operations": "基建營運",
    # 能源
    "Oil & Gas Integrated": "綜合石油", "Oil & Gas E&P": "石油勘探及生產", "Oil & Gas Midstream": "石油中游",
    "Oil & Gas Refining & Marketing": "煉油", "Oil & Gas Equipment & Services": "油田設備及服務",
    "Oil & Gas Drilling": "鑽油", "Thermal Coal": "動力煤", "Uranium": "鈾",
    # 原材料
    "Gold": "金礦", "Silver": "銀礦", "Copper": "銅", "Other Precious Metals & Mining": "其他貴金屬",
    "Other Industrial Metals & Mining": "其他工業金屬", "Steel": "鋼鐵", "Aluminum": "鋁", "Chemicals": "化工",
    "Specialty Chemicals": "特種化工", "Agricultural Inputs": "農業原料", "Building Materials": "建築材料",
    "Lumber & Wood Production": "木材", "Paper & Paper Products": "紙業", "Coking Coal": "焦煤",
    # 地產
    "REIT - Specialty": "特種房託", "REIT - Industrial": "工業房託", "REIT - Retail": "零售房託",
    "REIT - Residential": "住宅房託", "REIT - Office": "寫字樓房託", "REIT - Healthcare Facilities": "醫療房託",
    "REIT - Hotel & Motel": "酒店房託", "REIT - Diversified": "綜合房託", "REIT - Mortgage": "按揭房託",
    "Real Estate Services": "地產服務", "Real Estate - Development": "地產發展", "Real Estate - Diversified": "綜合地產",
    # 公用事業
    "Utilities - Regulated Electric": "電力", "Utilities - Renewable": "可再生能源",
    "Utilities - Diversified": "綜合公用事業", "Utilities - Regulated Gas": "燃氣", "Utilities - Regulated Water": "水務",
    "Utilities - Independent Power Producers": "獨立發電",
}


def zh(sector: str, industry: str) -> tuple[str, str]:
    return SECTOR_ZH.get(sector, sector or ""), INDUSTRY_ZH.get(industry, industry or "")
