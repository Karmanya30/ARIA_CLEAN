import re

import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, List


class Screener:
    """
    Python scraper that mirrors screener-scraper-pro functionality.
    Returns year-keyed dicts so callers can look up specific fiscal years.
    """
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/91.0.4472.124 Safari/537.36'
        }

    def _scrape_table(self, soup, section_id: str) -> Dict[str, Any]:
        """
        Scrape a table from a screener.in section.
        Returns:
            {
              "__columns__": ["Mar 2021", "Mar 2022", ...],   # year headers
              "Row Name":    {"Mar 2021": "1,234", ...},      # year-keyed values
              ...
            }
        """
        section = soup.find(id=section_id)  # a <section> (statements) or a <div> (shareholding tables)
        if not section:
            return {}
        table = section.find('table')
        if not table:
            return {}

        rows = table.find_all('tr')
        if not rows:
            return {}

        # First row = column headers (years)
        header_cells = rows[0].find_all(['td', 'th'])
        columns: List[str] = [c.text.strip() for c in header_cells[1:]]  # skip first empty cell

        result: Dict[str, Any] = {"__columns__": columns}

        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            row_key = cells[0].text.strip().replace('+', '').strip()
            if not row_key:
                continue
            values = [c.text.strip() for c in cells[1:]]
            # Store as year-keyed dict
            result[row_key] = dict(zip(columns, values))

        return result

    @staticmethod
    def _pledged_pct(soup) -> Any:
        """Percent of the promoters' holding that is pledged, when screener.in's automated remarks flag it
        ("Promoters have pledged 73.0% of their holding"). They only do so when it is material, so None means
        "not flagged", not "no pledge"."""
        for li in soup.select("div.pros li, div.cons li"):
            m = re.search(r"pledged\s+([\d.]+)\s*%", li.get_text(" ", strip=True))
            if m:
                return float(m.group(1))
        return None

    def get_company_data(self, company_name: str, consolidated: bool = False) -> Dict[str, Any]:
        company_name = company_name.upper().strip()

        # Default: standalone first (matches official annual report Schedule 4 figures for
        # banks), consolidated if standalone 404s. ``consolidated=True`` flips the order:
        # valuation needs the group figures, because market cap and EPS are consolidated
        # (Reliance: standalone TTM EPS 28.98 vs consolidated 55.22 == Yahoo's 55.21).
        base = f"https://www.screener.in/company/{company_name}/"
        urls = [base + "consolidated/", base] if consolidated else [base, base + "consolidated/"]

        res = requests.get(urls[0], headers=self.headers, timeout=20)
        if res.status_code == 404:
            res = requests.get(urls[1], headers=self.headers, timeout=20)

        if res.status_code != 200:
            raise Exception(f"Company '{company_name}' not found on Screener.in (status {res.status_code})")

        soup = BeautifulSoup(res.text, 'html.parser')

        return {
            "quarterly_results": self._scrape_table(soup, "quarters"),
            "profit_loss":       self._scrape_table(soup, "profit-loss"),
            "balance_sheet":     self._scrape_table(soup, "balance-sheet"),
            "cash_flow":         self._scrape_table(soup, "cash-flow"),
            "ratios":            self._scrape_table(soup, "ratios"),
            "shareholding":      self._scrape_table(soup, "quarterly-shp"),  # promoters / FIIs / DIIs / public, last 12 quarters
            "pledged_pct":       self._pledged_pct(soup),
            # Screener redirects /consolidated/ to the standalone page when a company has
            # no group accounts, so the final URL (not the one requested) says which we got.
            "view": "consolidated" if res.url.rstrip("/").endswith("/consolidated") else "standalone",
        }


def get_screener_data(company_name: str, consolidated: bool = False) -> Dict[str, Any]:
    """
    Fetch financial data for a given company from Screener.in.

    Returns structured year-keyed data (plus ``view``: "standalone"/"consolidated" --
    which statements these are) or {"error": "..."} on failure.
    """
    try:
        screener = Screener()
        data = screener.get_company_data(company_name, consolidated=consolidated)
        return {
            "ratios":            data.get("ratios", {}),
            "profit_loss":       data.get("profit_loss", {}),
            "balance_sheet":     data.get("balance_sheet", {}),
            "cash_flow":         data.get("cash_flow", {}),
            "quarterly_results": data.get("quarterly_results", {}),
            "shareholding":      data.get("shareholding", {}),
            "pledged_pct":       data.get("pledged_pct"),
            "view":              data.get("view", "standalone"),
        }
    except Exception as e:
        return {"error": f"Failed to fetch data for '{company_name}': {str(e)}"}

