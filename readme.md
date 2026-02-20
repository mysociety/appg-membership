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

### Ineligible Person IDs

The system maintains a list of ineligible person IDs in `models.py` - these are MPs who cannot be part of any APPG (e.g - government whips). When person IDs are assigned, any member or officer matching an ineligible person ID will automatically have their `removed` field set to `True`. This ensures they are excluded from the final dataset export while maintaining the historical record of their involvement.

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


### 7. Load Manual Membership Data

```bash
project load-manual-data
```

This downloads and processes manual APPG membership data from Google Docs. This file: https://docs.google.com/document/d/1IzlRjxXyT8qmU3_-xLO3z_VmTnPIjkb1Hz6SFtkBnKs/edit?tab=t.0#heading=h.pc6wfp5a5op2 

 The command will:
- Download a Google Docs document as markdown (or use `--skip-download` to use an existing file)
- Parse the document structure where:
  - H1: Ignored
  - H2: APPG title  
  - H3: Either "notes" (ignored) or "members" (processed)
  - If no H3s under H2, all content is treated as members
- Match APPG titles to existing files using flexible matching
- Update membership lists with `source_method: "manual"`
- Only update APPGs that currently have `empty` or `manual` source methods

**Options:**
- `--skip-download`: Skip downloading and use existing markdown file at `data/raw/manual/manual_membership.md`
- `--slug <appg-slug>`: Update only the specified APPG slug instead of processing all APPGs in the document

**Examples:**
```bash
# Update all APPGs from the Google Doc
project load-manual-data

# Update only a specific APPG
project load-manual-data --slug artificial-intelligence

# Update a specific APPG using existing markdown file
project load-manual-data --skip-download --slug climate-change
```

### 8. Add Person IDs to Members

```bash
project add-person-ids
```

This matches member names to known parliament members and assigns IDs.

**Automatic Removal of Ineligible Members:**
During this process, the system automatically checks against a list of ineligible person IDs (defined in `models.py`). Any member or officer whose person ID appears in the `ineligible_person_ids` set will have their `removed` field set to `True`. This handles cases where MPs are suspended, have resigned, or are otherwise ineligible to participate in APPGs.

To add a new ineligible person ID:
1. Edit `src/appg_membership/models.py`
2. Add the person ID to the `ineligible_person_ids` set:
   ```python
   ineligible_person_ids = {
       "uk.org.publicwhip/person/26384",
       "uk.org.publicwhip/person/NEW_ID_HERE",  # Add new ineligible IDs here
   }
   ```

### 9. Correct Unmatched Names

```bash
project correct-unmatched-names
```

This interactive tool helps fix name mismatches:
- Shows potential matches for unmatched names
- Lets you select the correct match or enter manually

### 10. Build the Final Dataset

```bash
project build
```

This compiles all the data into the final package format. The system will automatically use the latest register date from `models.py`.

### 11. Generate Diffs Between Registers

```bash
project generate-diffs
```

This creates diff reports showing what changed between consecutive registers, which are saved to:
- `data/interim/diffs/` (JSON format)
- `docs/_diffs/` (Markdown format for the Jekyll site)


### 12. Verify the Results

After completing these steps, check:
1. New JSON files in `data/appgs/` are correctly updated
2. The diff report in `docs/_diffs/` shows expected changes
3. The website records the appropriate number of accepted/rejected sites
4. Membership information has been extracted where available

### 13. Export Data for External Crowdsourcing (Optional)

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

### 13. Export Data for External Crowdsourcing (Optional)

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

### 14. Review Outdated Membership Lists

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

### 15. Remove Outdated Membership Lists

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

### 16. Rebuild the Documentation Site (if hosting)

Run the Jekyll build process to update the documentation site with the new diffs.

## Scotland Cross-Party Groups

In addition to UK Parliament APPGs, this system can download and process Cross-Party Group data from the Scottish Parliament.

### Downloading Scotland Data

```bash
project scotland
```

This command will:
- Fetch all current Cross-Party Groups from the Scottish Parliament API
- Download member roles and membership data
- Use the MySoc Popolo library to get person details with TWFY/MNIS IDs
- Generate public parliament.scot URLs for each group
- Save one JSON file per group in `data/cpg_scotland/`

The output files follow the same format as UK APPGs for consistency, with:
- `parliament` field set to "scotland"
- `member_type` set to "other" (since Scotland uses MSPs, not MPs)
- Public URLs pointing to the official parliament.scot Cross-Party Group pages
- Full officer and member information where available

### Scotland Data Sources

- **Scottish Parliament API**: https://data.parliament.scot/api/
  - Cross-Party Groups: `/crosspartygroups/json`
  - Roles: `/crosspartygrouproles/json` 
  - Members: `/membercrosspartyroles/json`
- **Person Data**: MySoc Popolo library with ScotParl identifiers
- **Public URLs**: parliament.scot Cross-Party Group pages

For more detailed information about the Scotland functionality, see [README_scotland.md](README_scotland.md).

## Senedd (Welsh Parliament) Cross-Party Groups

This system can also download and process Cross-Party Group data from the Senedd (Welsh Parliament). Both English and Welsh language versions are scraped and stored separately.

### Downloading Senedd Data

```bash
project senedd
```

This command will:
- Fetch the list of Cross-Party Groups from `business.senedd.wales`
- For each group, fetch both the English and Welsh language detail pages
- Extract name, purpose, officers, and members from each page
- Save one JSON file per group in `data/cpg_senedd_en/` (English) and `data/cpg_senedd_cy/` (Welsh)
- Mark membership data as `official` source method

The English and Welsh versions are treated as separate parliaments (`senedd-en` and `senedd-cy`) to mirror how they will eventually be presented in TheyWorkForYou.

The output files follow the same format as UK APPGs for consistency, with:
- `parliament` field set to `"senedd-en"` or `"senedd-cy"`
- `member_type` set to `"ms"` (Member of the Senedd)
- Officer roles detected in both English (Chair, Vice-Chair, Secretary) and Welsh (Cadeirydd, Is-Gadeirydd, Ysgrifennydd)
- Source URLs pointing to the official Senedd ModernGov pages

### Senedd Data Sources

- **English listing page**: https://business.senedd.wales/mgListOutsideBodiesByCategory.aspx
- **English detail pages**: `https://business.senedd.wales/mgOutsideBodyDetails.aspx?ID={id}`
- **Welsh detail pages**: `https://busnes.senedd.cymru/mgOutsideBodyDetails.aspx?ID={id}`

## Northern Ireland Assembly All-Party Groups

This system can also download and process All-Party Group data from the Northern Ireland Assembly.

### Downloading NI Assembly Data

```bash
project ni-assembly
```

This command will:
- Fetch all current All-Party Groups from the NI Assembly organisations API
- Download member roles and filter to APG role assignments
- Scrape purpose and financial benefits from detail pages
- Save one JSON file per group in `data/apg_ni/`
- Mark membership data as `official` source method

The output files follow the same format as UK APPGs for consistency, with:
- `parliament` field set to `"ni"`
- `member_type` set to `"mla"` (Member of the Legislative Assembly)
- Officer roles detected: Chairperson, Vice-Chairperson, Secretary, Treasurer
- Members deduplicated per group, preferring officer roles over member roles

### NI Assembly Data Sources

- **Current groups**: `https://data.niassembly.gov.uk/organisations.asmx/GetAllPartyGroupsListCurrent_JSON`
- **Member roles**: `https://data.niassembly.gov.uk/members.asmx/GetAllMemberRoles_JSON`
- **Detail pages**: `https://aims.niassembly.gov.uk/mlas/apgdetails.aspx?&cid={id}`
