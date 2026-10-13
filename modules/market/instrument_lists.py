"""Curated instrument lists (Yahoo Finance symbols) for the categories that have no free exchange-wide master file.
Each entry is "SYMBOL|Name". Everything here was checked against Yahoo before being listed."""

INDICES = """^NSEI|Nifty 50
^BSESN|BSE Sensex
^NSEBANK|Nifty Bank
^CNXIT|Nifty IT
^NSMIDCP|Nifty Next 50
^CRSLDX|Nifty 500
^CNXSC|Nifty Smallcap 100
^INDIAVIX|India VIX
^CNXAUTO|Nifty Auto
^CNXPHARMA|Nifty Pharma
^CNXFMCG|Nifty FMCG
^CNXMETAL|Nifty Metal
^CNXENERGY|Nifty Energy
^CNXREALTY|Nifty Realty
^CNXPSUBANK|Nifty PSU Bank
^CNXMEDIA|Nifty Media
^GSPC|S&P 500
^DJI|Dow Jones Industrial Average
^IXIC|Nasdaq Composite
^NDX|Nasdaq 100
^RUT|Russell 2000
^VIX|CBOE Volatility Index (VIX)
^FTSE|FTSE 100
^GDAXI|DAX (Germany)
^FCHI|CAC 40 (France)
^N225|Nikkei 225 (Japan)
^HSI|Hang Seng (Hong Kong)
^STI|Straits Times (Singapore)
^AXJO|S&P/ASX 200 (Australia)
^KS11|KOSPI (South Korea)
000001.SS|Shanghai Composite
^BVSP|Bovespa (Brazil)
DX-Y.NYB|US Dollar Index"""

COMMODITIES = """GC=F|Gold
SI=F|Silver
PL=F|Platinum
PA=F|Palladium
HG=F|Copper
CL=F|Crude Oil (WTI)
BZ=F|Brent Crude Oil
NG=F|Natural Gas
RB=F|Gasoline (RBOB)
HO=F|Heating Oil
ZC=F|Corn
ZW=F|Wheat
ZS=F|Soybeans
KC=F|Coffee
SB=F|Sugar
CT=F|Cotton
CC=F|Cocoa
LE=F|Live Cattle"""

CURRENCIES = """USDINR=X|US Dollar / Indian Rupee
EURINR=X|Euro / Indian Rupee
GBPINR=X|British Pound / Indian Rupee
JPYINR=X|Japanese Yen / Indian Rupee
AEDINR=X|UAE Dirham / Indian Rupee
SGDINR=X|Singapore Dollar / Indian Rupee
AUDINR=X|Australian Dollar / Indian Rupee
CADINR=X|Canadian Dollar / Indian Rupee
CHFINR=X|Swiss Franc / Indian Rupee
CNYINR=X|Chinese Yuan / Indian Rupee
EURUSD=X|Euro / US Dollar
GBPUSD=X|British Pound / US Dollar
USDJPY=X|US Dollar / Japanese Yen
AUDUSD=X|Australian Dollar / US Dollar
NZDUSD=X|New Zealand Dollar / US Dollar
USDCAD=X|US Dollar / Canadian Dollar
USDCHF=X|US Dollar / Swiss Franc
USDCNY=X|US Dollar / Chinese Yuan
USDSGD=X|US Dollar / Singapore Dollar
USDHKD=X|US Dollar / Hong Kong Dollar"""

# yields: the quoted number is a percentage yield, not a price
BOND_YIELDS = """^TNX|US 10-Year Treasury Yield
^FVX|US 5-Year Treasury Yield
^IRX|US 13-Week Treasury Bill Yield
^TYX|US 30-Year Treasury Yield"""

BOND_ETFS_GLOBAL = """TLT|iShares 20+ Year Treasury Bond ETF
IEF|iShares 7-10 Year Treasury Bond ETF
SHY|iShares 1-3 Year Treasury Bond ETF
BND|Vanguard Total Bond Market ETF
AGG|iShares Core US Aggregate Bond ETF
LQD|iShares Investment Grade Corporate Bond ETF
HYG|iShares High Yield Corporate Bond ETF
TIP|iShares TIPS Bond ETF
EMB|iShares JP Morgan USD Emerging Markets Bond ETF
BNDX|Vanguard Total International Bond ETF
MUB|iShares National Muni Bond ETF
GOVT|iShares US Treasury Bond ETF"""

# Indian ETFs listed on NSE (the NSE/BSE universe file only carries ordinary equities and BSE-only ETFs)
ETFS_INDIA = """NIFTYBEES.NS|Nippon India ETF Nifty 50 BeES
BANKBEES.NS|Nippon India ETF Nifty Bank BeES
JUNIORBEES.NS|Nippon India ETF Nifty Next 50 Junior BeES
GOLDBEES.NS|Nippon India ETF Gold BeES
SILVERBEES.NS|Nippon India Silver ETF
ITBEES.NS|Nippon India ETF Nifty IT
PSUBNKBEES.NS|Nippon India ETF PSU Bank BeES
INFRABEES.NS|Nippon India ETF Infra BeES
PHARMABEES.NS|Nippon India ETF Nifty Pharma
AUTOBEES.NS|Nippon India ETF Nifty Auto
CONSUMBEES.NS|Nippon India ETF Nifty India Consumption
MID150BEES.NS|Nippon India ETF Nifty Midcap 150
HNGSNGBEES.NS|Nippon India ETF Hang Seng BeES
CPSEETF.NS|CPSE ETF
MON100.NS|Motilal Oswal Nasdaq 100 ETF
MAFANG.NS|Mirae Asset NYSE FANG+ ETF
MOM100.NS|Motilal Oswal Midcap 100 ETF
SETFNIF50.NS|SBI ETF Nifty 50
SETFNN50.NS|SBI ETF Nifty Next 50
SBIETFQLTY.NS|SBI ETF Quality
SBIETFIT.NS|SBI ETF Nifty IT
ICICIB22.NS|ICICI Prudential Bharat 22 ETF
NIFTYIETF.NS|ICICI Prudential Nifty 50 ETF
SENSEXIETF.NS|ICICI Prudential Sensex ETF
BSLGOLDETF.NS|Aditya Birla Sun Life Gold ETF
HDFCNIFTY.NS|HDFC Nifty 50 ETF
HDFCSENSEX.NS|HDFC Sensex ETF
HDFCGOLD.NS|HDFC Gold ETF
LICNETFN50.NS|LIC MF Nifty 50 ETF
LICNETFSEN.NS|LIC MF Sensex ETF
TATAGOLD.NS|Tata Gold ETF
MOM50.NS|Motilal Oswal Nifty 50 ETF
LOWVOLIETF.NS|ICICI Prudential Nifty Low Vol 30 ETF"""

# Indian bond / liquid / gilt ETFs on NSE
BOND_ETFS_INDIA = """LIQUIDBEES.NS|Nippon India ETF Liquid BeES
LIQUIDCASE.NS|Zerodha Nifty Liquid ETF
LIQUIDETF.NS|ICICI Prudential Liquid ETF
EBBETF0430.NS|Bharat Bond ETF April 2030
EBBETF0431.NS|Bharat Bond ETF April 2031
EBBETF0433.NS|Bharat Bond ETF April 2033
LTGILTBEES.NS|Nippon India ETF Long Term Gilt
GILT5YBEES.NS|Nippon India ETF 5 Year Gilt
GSEC10IETF.NS|ICICI Prudential Nifty 10 yr Benchmark G-Sec ETF"""

ETFS_GLOBAL = """SPY|SPDR S&P 500 ETF Trust
VOO|Vanguard S&P 500 ETF
IVV|iShares Core S&P 500 ETF
QQQ|Invesco QQQ Trust (Nasdaq 100)
VTI|Vanguard Total Stock Market ETF
DIA|SPDR Dow Jones Industrial Average ETF
IWM|iShares Russell 2000 ETF
VT|Vanguard Total World Stock ETF
VEA|Vanguard FTSE Developed Markets ETF
VWO|Vanguard FTSE Emerging Markets ETF
EFA|iShares MSCI EAFE ETF
EEM|iShares MSCI Emerging Markets ETF
INDA|iShares MSCI India ETF
INDY|iShares India 50 ETF
EPI|WisdomTree India Earnings Fund
SMIN|iShares MSCI India Small-Cap ETF
XLK|Technology Select Sector SPDR Fund
XLF|Financial Select Sector SPDR Fund
XLE|Energy Select Sector SPDR Fund
XLV|Health Care Select Sector SPDR Fund
XLY|Consumer Discretionary Select Sector SPDR Fund
XLP|Consumer Staples Select Sector SPDR Fund
XLI|Industrial Select Sector SPDR Fund
XLU|Utilities Select Sector SPDR Fund
SOXX|iShares Semiconductor ETF
SMH|VanEck Semiconductor ETF
ARKK|ARK Innovation ETF
VNQ|Vanguard Real Estate ETF
VIG|Vanguard Dividend Appreciation ETF
VYM|Vanguard High Dividend Yield ETF
SCHD|Schwab US Dividend Equity ETF
GLD|SPDR Gold Shares
IAU|iShares Gold Trust
SLV|iShares Silver Trust
USO|United States Oil Fund
IBIT|iShares Bitcoin Trust ETF
FBTC|Fidelity Wise Origin Bitcoin Fund
ETHA|iShares Ethereum Trust ETF"""

# top coins by market cap as "SYMBOL|Name[|Yahoo symbol when it is not SYMBOL-USD]"; used when CoinGecko is unreachable and to name coins it returns
CRYPTO = """BTC|Bitcoin
ETH|Ethereum
USDT|Tether
XRP|XRP
BNB|BNB
SOL|Solana
USDC|USD Coin
DOGE|Dogecoin
TRX|TRON
ADA|Cardano
STETH|Lido Staked Ether
LINK|Chainlink
AVAX|Avalanche
XLM|Stellar
SHIB|Shiba Inu
TON|Toncoin
SUI|Sui|SUI20947-USD
HBAR|Hedera
BCH|Bitcoin Cash
DOT|Polkadot
LTC|Litecoin
UNI|Uniswap|UNI7083-USD
XMR|Monero
PEPE|Pepe|PEPE24478-USD
ICP|Internet Computer
NEAR|NEAR Protocol
APT|Aptos|APT21794-USD
ETC|Ethereum Classic
AAVE|Aave
CRO|Cronos
ATOM|Cosmos
ARB|Arbitrum
VET|VeChain
FIL|Filecoin
ALGO|Algorand
OP|Optimism
INJ|Injective
RENDER|Render
GRT|The Graph|GRT6719-USD
IMX|Immutable|IMX10603-USD
STX|Stacks|STX4847-USD
TIA|Celestia
SEI|Sei
LDO|Lido DAO
MKR|Maker
RUNE|THORChain
SAND|The Sandbox
MANA|Decentraland
AXS|Axie Infinity
THETA|Theta Network
FLOW|Flow
XTZ|Tezos
EOS|EOS
KAS|Kaspa
BONK|Bonk
WIF|dogwifhat
FLOKI|Floki
CRV|Curve DAO
COMP|Compound|COMP5692-USD
SNX|Synthetix
1INCH|1inch
ENJ|Enjin Coin
CHZ|Chiliz
GALA|Gala
APE|ApeCoin
DYDX|dYdX
ZEC|Zcash
DASH|Dash
NEO|Neo
IOTA|IOTA
KAVA|Kava
ZIL|Zilliqa
BAT|Basic Attention Token
QNT|Quant
EGLD|MultiversX
FET|Artificial Superintelligence Alliance
JUP|Jupiter
ENA|Ethena
PYTH|Pyth Network
WLD|Worldcoin
ONDO|Ondo
POL|POL (ex-MATIC)|POL28321-USD
S|Sonic|S32684-USD
TAO|Bittensor|TAO22974-USD
AERO|Aerodrome Finance
PENDLE|Pendle
JASMY|JasmyCoin
GNO|Gnosis
RAY|Raydium
CAKE|PancakeSwap
LRC|Loopring
YFI|yearn.finance
SUSHI|SushiSwap
ANKR|Ankr
ICX|ICON
ZRX|0x"""
