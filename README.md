# Audiobook Narrator Review Tool

This project provides a complete workflow for proof-listening and validating audiobook recordings against their original manuscript. It helps identify discrepancies such as substitutions, deletions, and insertions made by the narrator.

The process is split into two main parts:
1.  **Transcription (Google Colab):** A Jupyter Notebook uses OpenAI's Whisper on a free GPU to transcribe audio files and generate precise, word-level timestamps, with support for batch processing multiple chapters.
2.  **Review (Desktop App):** A Python/Tkinter application loads the manuscript, the audio, and the generated timestamps. It provides an interactive interface to play the audio, see the text with highlighted errors, and export a report.

## Core Features

- **Accurate Transcription:** Leverages OpenAI's Whisper for high-quality, multilingual audio-to-text transcription.
- **Batch Processing:** The Colab notebook can process multiple audio chapters in a single run.
- **Automated Error Detection:** Uses `difflib` to compare the manuscript with the transcription and flag potential mistakes.
- **Synchronized Playback:** "Karaoke-style" word highlighting follows the narrator's speech in real-time.
- **Interactive UI:**
    - Play, pause, rewind, and adjust playback speed.
    - Click on any word to jump to that point in the audio.
    - Navigate between paragraphs.
- **Confidence Filtering:** A sensitivity slider allows you to filter out low-confidence transcription errors, reducing noise.
- **CSV Export:** Export a list of confirmed or potential errors with timestamps for easy reporting.

## The Workflow

The two files work together to create a streamlined process:

```
[Your Manuscript.docx] + [Your Audio Chapters.mp3]
      |
      |  (Step 1: Process in Google Colab)
      V
[audiobook_validation.ipynb] --> [Chapter 1_timestamps.json], [Chapter 2_timestamps.json], etc.
      |
      |  (Step 2: Load one chapter's files into the Desktop App)
      V
[review_app.py] --> [Error_Report.csv]
```

## Installation and Setup

### Prerequisites

- A Google Account (for using Google Colab and Google Drive).
- Python 3.7+ installed on your local machine.

### Installation Steps

1.  **Clone or download the repository:**
    ```sh
    git clone https://github.com/lilfetz22/audiobook_validation.git
    cd audiobook_validation
    ```

2.  **Install the required Python packages for the desktop app:**
    A `requirements.txt` file is included. Run the following command in your terminal:
    ```sh
    pip install -r requirements.txt
    ```

## Usage Guide

Follow these steps to get up and running.

### Part 1: Generate Timestamps with Google Colab

This step transcribes your audio files in batches to create the necessary data for the review app.

1.  **Upload Audio Files to Google Drive:**
    - Open your Google Drive.
    - Create a single folder for your project (e.g., `My Drive/Audiobook Project`).
    - Upload all your audiobook chapter `.mp3` files into this folder.

2.  **Open and Configure the Notebook:**
    - Upload `audiobook_validation.ipynb` to your Google Drive and open it with Google Colab.
    - Run the first few cells to mount your drive and install the necessary libraries.
    - Go to the **"Step 4: Configure Batch Processing"** cell. You will see an interactive form.

    <!-- A future update could include an image of the Colab form here -->

    - **Fill out the form fields:**
        1.  `directory_path`: In the Colab file browser on the left, find the folder where you uploaded your audio files. Right-click it and select **"Copy path"**. Paste this path into the field.
        2.  `file_name_template`: Enter the naming pattern for your files, using `{num}` as a placeholder for the chapter number.
            - *Example:* If your files are named `Chapter 1.mp3`, `Chapter 2.mp3`, etc., you would enter: `Chapter {num}.mp3`
            - *Example:* If your files are named `1 - ADP.mp3`, `2 - ADP.mp3`, etc., you would enter: `{num} - ADP.mp3`
        3.  `start_chapter` and `end_chapter`: Enter the range of chapter numbers you want to process (e.g., from `1` to `15`).

3.  **Run the Transcription:**
    - Run the **"Step 4"** configuration cell. It will validate your settings and show you which files it expects to find. If you see any errors, correct them.
    - In Colab, go to `Runtime` -> `Change runtime type` and select `T4 GPU` as the hardware accelerator. This will speed up transcription significantly.
    - Run the **"Step 5: Run Transcription on All Chapters"** cell. The notebook will now loop through your specified chapters, transcribing each one. This may take several minutes to hours, depending on the number and length of your files.

4.  **Get the Output:**
    - Once finished, a `_timestamps.json` file will be generated for **each successfully processed chapter**, saved in the same Google Drive folder.
    - Download all the necessary JSON files (and their corresponding MP3s and DOCX manuscript) to your computer.

### Part 2: Review with the Desktop Application

Now you can use the desktop app to review each chapter.

1.  **Run the Application:**
    - Open a terminal or command prompt.
    - Navigate to the project folder where `review_app.py` is located.
    - Run the command: `python review_app.py`

2.  **Load a Chapter for Review:**
    - The application window will open. Click the **"Load Files..."** button.
    - A series of file dialogs will appear. Select the files for a **single chapter** in the requested order:
        1.  First, the `.docx` manuscript.
        2.  Second, the corresponding `_timestamps.json` file for that chapter.
        3.  Third, the corresponding `.mp3` audio file for that chapter.
    - The app will process the data and display the manuscript text.

3.  **Use the App:**
    - Potential errors will be highlighted:
        - <span style="background-color:#FFDDDD;">Substitutions</span> are highlighted in light red.
        - <span style="background-color:#FFFFCC; text-decoration:line-through;">Deletions</span> are highlighted in yellow with a strikethrough.
    - Use the playback controls at the bottom to listen. The currently spoken word will be highlighted in light blue.
    - Use the **Confidence Threshold** slider on the right to hide/show mismatches.
    - When you are ready, click **"Export Confirmed Errors (CSV)"** to generate a report.

## Known Limitations & Future Improvements

- **Context Menu:** The right-click context menu to "Confirm" or "Ignore" an error is a placeholder. The logic to precisely identify which highlighted error was clicked on needs to be implemented. Currently, the export function saves all *visible* mismatches.
- **Word Mapping:** The logic for mapping a character position back to a specific word can be imprecise in complex paragraphs, affecting the `click-to-seek` feature.