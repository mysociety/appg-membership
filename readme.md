
# APPG Membership

Scraper and raw data for UK Parliament APPG information.

This is an experiment in AI-assisted scraping - several different agent approaches are being applied at different steps of the process.

## Steps

### Parliamentary register scrape

The register scraper is a normal scraper (although the basic approach started as being AI written based on a provided sample of a page). This extracts the basic information about the APPG and its officers.

### Missing website search

There is then a search agent which uses openai and tavity to look for website of APPGs. where there wasn't a provided url. In the initial run, this identified 74 candidates - of which 45 were valid (invalid ones were news articles, appgs in other parliaments, or sites for previous iterations.)

### Membership scrape

Branching out from where we know the website, an agent looks for a membership page, and returns a membership list and the page it was found on. We then validate this by checking that all mentioned named appear on the website scraped (early errors here were generally formatting corrections). This is sometimes creating duplicate names - but we correct this in a future step.

### Manual info

We are storing some membership lists from information requests in data/raw/september. We'll want a different process to handle results from emails. 

## Parliament ID assignment

This is handled through automatic matching to people.json - and a spelling reconciliation tool. 
