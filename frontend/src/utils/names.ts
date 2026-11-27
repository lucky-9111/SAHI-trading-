/** Display names for symbols the home screen shows. The instrument master has only ticker symbols. */
export const STOCK_NAMES: Record<string, string> = {
  RELIANCE: "Reliance Industries", TCS: "Tata Consultancy Services", INFY: "Infosys", HDFCBANK: "HDFC Bank", ICICIBANK: "ICICI Bank",
  SBIN: "State Bank of India", ITC: "ITC", LT: "Larsen & Toubro", BHARTIARTL: "Bharti Airtel", AXISBANK: "Axis Bank",
  KOTAKBANK: "Kotak Mahindra Bank", HINDUNILVR: "Hindustan Unilever", TATAMOTORS: "Tata Motors", MARUTI: "Maruti Suzuki",
  SUNPHARMA: "Sun Pharmaceutical", WIPRO: "Wipro", TATASTEEL: "Tata Steel", SONACOMS: "Sona BLW Precision",
  NIFTYBEES: "Nippon Nifty ETF", BANKBEES: "Nippon Bank ETF", JUNIORBEES: "Nippon Junior BeES", GOLDBEES: "Nippon Ind ETF Gold BeES",
  SILVERBEES: "Nippon Silver ETF", LIQUIDBEES: "Nippon Liquid BeES", ITBEES: "Nippon IT ETF", PSUBNKBEES: "Nippon PSU Bank ETF",
  SETFNIF50: "SBI Nifty ETF", NIFTYIETF: "ICICI Pru Nifty ETF", HDFCNIFTY: "HDFC Nifty ETF", SETFNIFBK: "SBI Nifty Bank ETF",
  BANKIETF: "ICICI Pru Bank ETF", LIQUIDIETF: "ICICI Pru Liquid ETF", HDFCGOLD: "HDFC Gold ETF", GOLDIETF: "ICICI Pru Gold ETF",
  SILVERIETF: "ICICI Pru Silver ETF", HDFCSILVER: "HDFC Silver ETF",
  NIFTY: "NIFTY50", BANKNIFTY: "BANKNIFTY", FINNIFTY: "FINNIFTY", MIDCPNIFTY: "MIDCPNIFTY",
};

export const COMMODITY_NAMES: Record<string, string> = {
  GOLD: "Gold", GOLDM: "Gold Mini", GOLDTEN: "Gold Ten", GOLDGUINEA: "Gold Guinea", GOLDPETAL: "Gold Petal",
  SILVER: "Silver", SILVERM: "Silver Mini", SILVERMIC: "Silver Micro", CRUDEOIL: "Crude Oil", CRUDEOILM: "Crude Oil Mini",
  NATURALGAS: "Natural Gas", NATGASMINI: "Natural Gas Mini", COPPER: "Copper", ZINC: "Zinc", ZINCMINI: "Zinc Mini",
  LEAD: "Lead", LEADMINI: "Lead Mini", ALUMINIUM: "Aluminium", ALUMINI: "Aluminium Mini", NICKEL: "Nickel",
  MENTHAOIL: "Mentha Oil", COTTON: "Cotton", CARDAMOM: "Cardamom",
};

export const displayName = (symbol: string): string => STOCK_NAMES[symbol] ?? COMMODITY_NAMES[symbol] ?? symbol;

/** Recently viewed instruments (this browser only). */
export interface Recent { symbol: string; exchange: string; at: number }
const KEY = "sahi_recent";
export function readRecent(): Recent[] {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "[]") as Recent[]; } catch { return []; }
}
export function pushRecent(symbol: string, exchange: string): void {
  try {
    const list = readRecent().filter((r) => !(r.symbol === symbol && r.exchange === exchange));
    list.unshift({ symbol, exchange, at: Date.now() });
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, 12)));
  } catch { /* storage unavailable */ }
}
