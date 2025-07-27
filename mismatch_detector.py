import difflib
import re
import time
import logging


def normalize_word(word):
    """A consistent normalization function used for comparison."""
    return word.lower().strip(".,;:!?\"'()[]{} ")


class MismatchDetector:
    """
    Analyzes manuscript and transcription data to find and categorize differences.
    """

    def __init__(self, manuscript_tokens, transcribed_data, full_manuscript_text):
        """
        Initializes the detector with the necessary data.

        Args:
            manuscript_tokens (list): A list of token dicts from the manuscript,
                                      including {'word': str, 'start': int, 'end': int}.
            transcribed_data (list): The list of word dicts from the JSON file.
            full_manuscript_text (str): The complete manuscript text for context extraction.
        """
        self.manuscript_tokens = manuscript_tokens
        self.transcribed_data = transcribed_data
        self.full_manuscript_text = full_manuscript_text
        logging.info("MismatchDetector initialized.")

    def find_mismatches(self):
        """
        Performs the core comparison and returns a list of mismatch objects.

        Returns:
            list: A list of dictionaries, where each dictionary represents a single mismatch.
        """
        logging.info("Starting mismatch detection process.")
        mismatches = []

        manuscript_normalized = [
            normalize_word(token["word"]) for token in self.manuscript_tokens
        ]
        transcribed_normalized = [
            normalize_word(item["word"]) for item in self.transcribed_data
        ]

        matcher = difflib.SequenceMatcher(
            None, manuscript_normalized, transcribed_normalized, autojunk=False
        )

        opcodes = matcher.get_opcodes()
        logging.info(f"SequenceMatcher found {len(opcodes)} opcodes.")

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                continue

            # --- Data Extraction from Slices ---
            manuscript_slice_tokens = self.manuscript_tokens[i1:i2]
            narrated_slice_data = self.transcribed_data[j1:j2]

            manuscript_text = " ".join(
                token["word"] for token in manuscript_slice_tokens
            )
            narrated_text = " ".join(item["word"] for item in narrated_slice_data)

            # --- Confidence Score Calculation ---
            confidence = 1.0  # Default confidence (especially for deletions)
            if narrated_slice_data:
                probs = [item.get("probability", 0.0) for item in narrated_slice_data]
                if probs:
                    confidence = sum(probs) / len(probs)

            # --- Timestamp Calculation ---
            # For insertions/replacements, use the start time of the first narrated word.
            # For deletions, estimate from the end time of the previous word.
            start_time = None
            if narrated_slice_data:
                start_time = narrated_slice_data[0]["start"]
            elif j1 > 0:
                start_time = self.transcribed_data[j1 - 1]["end"]

            # --- Context Sentence Extraction ---
            # Get the character index of the start of the mismatch in the manuscript
            context_char_index = -1
            if manuscript_slice_tokens:
                context_char_index = manuscript_slice_tokens[0]["start"]
            # If it's an pure insertion, find the context of the word *after* the insertion
            elif self.manuscript_tokens and i1 < len(self.manuscript_tokens):
                context_char_index = self.manuscript_tokens[i1]["start"]

            context_sentence = self._get_context_sentence(context_char_index)

            mismatches.append(
                {
                    "type": tag,  # 'replace', 'delete', 'insert'
                    "manuscript_text": manuscript_text,
                    "narrated_text": narrated_text,
                    "start_time": start_time,
                    "confidence": confidence,
                    "manuscript_indices": (
                        i1,
                        i2,
                    ),  # For mapping back to the manuscript tokens
                    "status": "unconfirmed",  # 'confirmed' or 'ignored'
                    "context": context_sentence,
                    "tooltip_text": (
                        f"Type: {tag.capitalize()}\n"
                        f"Confidence: {confidence:.2%}\n"
                        f"Manuscript: '{manuscript_text}'\n"
                        f"Narrated: '{narrated_text}'"
                    ),
                }
            )

        logging.info(
            f"Mismatch detection complete. Found {len(mismatches)} potential mismatches."
        )
        return mismatches

    def _get_context_sentence(self, char_index):
        """
        Finds the full sentence that contains the character at a given index.
        """
        if char_index == -1 or not self.full_manuscript_text:
            return "N/A"

        # Find the start of the sentence (search backwards for . ! ?)
        sentence_start = self.full_manuscript_text.rfind(".", 0, char_index)
        sentence_start = max(
            sentence_start, self.full_manuscript_text.rfind("!", 0, char_index)
        )
        sentence_start = max(
            sentence_start, self.full_manuscript_text.rfind("?", 0, char_index)
        )

        # Find the end of the sentence (search forwards)
        sentence_end = self.full_manuscript_text.find(".", char_index)
        if sentence_end == -1:
            sentence_end = len(self.full_manuscript_text)

        exclamation_end = self.full_manuscript_text.find("!", char_index)
        if exclamation_end != -1:
            sentence_end = min(sentence_end, exclamation_end)

        question_end = self.full_manuscript_text.find("?", char_index)
        if question_end != -1:
            sentence_end = min(sentence_end, question_end)

        # Extract and clean up the sentence
        context = self.full_manuscript_text[
            sentence_start + 1 : sentence_end + 1
        ].strip()
        return context
