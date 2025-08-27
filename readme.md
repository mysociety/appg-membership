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

## Updating When a New APPG Register is Released

When a new APPG register is published, follow these steps to update the system:

### 1. Update the Register Date in models.py

1. Open `/src/appg_membership/models.py`
2. Add the new register date to the `register_dates` list at the top of the file
   ```python
   register_dates = [
       "240828",  # 28 August 2024
       "241009",  # 9 October 2024
       "241120",  # 20 November 2024
       "250102",  # 2 January 2025
       "250212",  # 12 February 2025
       "250328",  # 28 March 2025
       "250507",  # 7 May 2025
       "YYMMDD",  # Add the new date here in format YYMMDD with a comment
   ]
   ```

### 2. Fetch the New Register

Run the following command to fetch only the latest register:

```bash
project fetch-appg-index --latest-only
```

This will:
- Download the APPG index from the UK Parliament website
- Parse the HTML for each APPG
- Save the data to JSON files in the `data/appgs/` directory
- Preserve any membership data from previous registers

### 3. Search for Missing Websites

```bash
project search-for-websites
```

This command will search for websites for APPGs that don't have one listed in the register, marking potential matches with 'search_precheck' status.

### 4. Review Website Candidates

```bash
project review-websites
```

This interactive tool allows you to review each automatically found website:
- **a**: Accept the URL as valid (status → 'search')
- **r**: Reject the URL as invalid (URL cleared, status → 'bad_search')
- **m**: Enter a different URL manually (status → 'manual')
- **s**: Skip this APPG for now (status remains 'search_precheck')
- **q**: Quit the review process and save progress

You can open each URL in a browser to verify it's the correct website before making a decision.

### 5. Scrape Membership Information

```bash
project scrape-memberships
```

This will attempt to extract membership lists from websites with 'search' or 'manual' status.

### 6. Load Membership Spreadsheets

```bash
project load-spreadsheets
```

This loads any available spreadsheets with membership information.

### 7. Add Person IDs to Members

```bash
project add-person-ids
```

This matches member names to known parliament members and assigns IDs.

### 8. Correct Unmatched Names

```bash
project correct-unmatched-names
```

This interactive tool helps fix name mismatches:
- Shows potential matches for unmatched names
- Lets you select the correct match or enter manually

### 9. Build the Final Dataset

```bash
project build
```

This compiles all the data into the final package format. The system will automatically use the latest register date from `models.py`.

### 10. Generate Diffs Between Registers

```bash
project generate-diffs
```

This creates diff reports showing what changed between consecutive registers, which are saved to:
- `data/interim/diffs/` (JSON format)
- `docs/_diffs/` (Markdown format for the Jekyll site)

### 11. Verify the Results

After completing these steps, check:
1. New JSON files in `data/appgs/` are correctly updated
2. The diff report in `docs/_diffs/` shows expected changes
3. The website records the appropriate number of accepted/rejected sites
4. Membership information has been extracted where available

### 12. Export Data for External Crowdsourcing (Optional)

If you need external help to verify websites and membership information that the automatic scraping couldn't find:

```bash
python -m appg_membership export_crowdsource
```

This creates an Excel spreadsheet with the following fields:
- `starting_status`: Current status (no_website, website, website_no_members, website_members_list)
- `review_status`: Blank column for crowdsourcers to fill
- `appg_slug`: Unique identifier for the APPG
- `appg_name`: Full name of the APPG
- `parliament_source_url`: URL to the official parliament page
- `google_link`: Pre-populated Google search link
- `appg_website`: Current website URL if available
- `appg_members_page`: Members page URL if available

The Excel file is saved to `data/exports/` with a timestamp in the filename, or you can specify a custom path:

```bash
python -m appg_membership export_crowdsource --output-path=/path/to/your/file.xlsx
```

### 13. Review Outdated Membership Lists

```bash
project find-old-members
```

This command helps review whether automatically sourced membership lists are out of date and should be removed. The purpose is to identify APPGs where the membership information may no longer be accurate because listed members are no longer serving in Parliament.

The command offers two output formats:

**List format (default):**
```bash
project find-old-members --format list
```
Shows individual messages for each person who is no longer in Parliament but still listed as an APPG member:
```
John Smith is listed as a member of artificial-intelligence but is no longer in Parliament
Jane Doe is listed as a member of climate-change but is no longer in Parliament
```

**Table format:**
```bash
project find-old-members --format table
```
Shows a summary table sorted by percentage of outdated members (highest first), helping prioritize which APPGs need the most urgent review:

| APPG Slug | Old Members | Total | Proportion |
|-----------|-------------|-------|------------|
| example-appg | 5 | 10 | 50.0% |

Use this information to:
- Identify APPGs with high percentages of former MPs that may need membership list updates
- Remove or flag outdated automatically sourced membership lists
- Prioritize APPGs for manual verification or re-scraping

### 14. Remove Outdated Membership Lists

When you identify APPGs with problematic membership lists (especially those marked as "Significant" in the table format), you can remove the outdated information:

```bash
project blank-membership-information <appg-slug>
```

This command will:
- Set the membership source method to 'empty'
- Remove all members from the membership list
- Clear source URLs and timestamps
- Save the changes to the APPG file

**Example:**
```bash
project blank-membership-information artificial-intelligence
```

**When to use this command:**
- APPGs with high proportions of former MPs (especially ≥33% marked as "Significant")
- Membership lists that are clearly outdated or inaccurate
- Cases where re-scraping is not feasible and manual verification shows the list is wrong

**What happens after blanking:**
- The APPG will show as having no membership information
- It can be re-scraped in future runs if a valid membership page becomes available
- The official officers from the parliamentary register remain unchanged

This approach is preferable to keeping inaccurate data, as it clearly indicates that membership information needs to be sourced rather than presenting outdated lists as current.

### 15. Rebuild the Documentation Site (if hosting)

Run the Jekyll build process to update the documentation site with the new diffs.
