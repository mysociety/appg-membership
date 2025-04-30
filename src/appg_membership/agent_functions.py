import io

import httpx
import PyPDF2
from markdownify import markdownify as md


def get_url_as_markdown(url: str) -> str:
    """
    Fetch a URL and return a reduced markdown version of the content.
    If the URL points to a PDF, extract its text content.
    """
    headers = {"User-Agent": "TWFY APPG Searcher"}
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
        if response.status_code != 200:
            return f"Failed to fetch the page: {response.status_code}"
    except httpx.RequestError as exc:
        return f"An error occurred while requesting the URL: {exc}"

    # Check if content is PDF
    content_type = response.headers.get("content-type", "")
    is_pdf = content_type.lower().startswith("application/pdf")

    # If URL doesn't specify content type, try to guess from URL
    if not is_pdf and url.lower().endswith(".pdf"):
        is_pdf = True

    content = response.content

    if is_pdf:
        try:
            # Extract text from PDF
            pdf_file = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)

            # Extract text from each page
            text_content = []
            for page in pdf_reader.pages:
                text_content.append(page.extract_text() or "")

            md_content = "\n\n".join(text_content)

            # Add PDF metadata as markdown header
            if pdf_reader.metadata:
                md_content = (
                    f"# {pdf_reader.metadata.title or 'PDF Document'}\n\n{md_content}"
                )

            return md_content
        except Exception as e:
            return f"Failed to process PDF content: {str(e)}"
    else:
        # Handle HTML content as before
        try:
            md_content = md(content.decode("utf-8"))
        except UnicodeDecodeError:
            return "Failed to decode the content. Please check the URL or the content type."

        # delete lines that start [![](data:image/svg+xml
        # remove all svg encoded images from the markdown content
        lines = md_content.splitlines()
        filtered_lines = []
        for line in lines:
            if "(data:image/svg+xml," not in line:
                filtered_lines.append(line)
        md_content = "\n".join(filtered_lines)

        # limit to first 20,000 characters
        md_content = md_content[:10000]

        # write the markdown content to a file
        with open("output.md", "w", encoding="utf-8") as f:
            f.write(md_content)
        return md_content
