"""Ensemble parser that combines multiple parsers with tie-breaking strategies.

This module implements various approaches to combine parser results:
1. Consensus voting
2. Confidence scoring
3. Source prioritization
4. Pattern validation
5. Historical comparison
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import os
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from email_parser.base import BaseParser, EmailData, InvestmentOpportunity, ParserResult
from email_parser.layout_attachment_parser import LayoutLLMParser
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser
from email_parser.utils import fuzzy_match_ebitda

load_dotenv()


class EnsembleParser(BaseParser):
    """Ensemble parser that combines multiple parsing approaches.

    Implements various tie-breaking strategies:
    - Majority voting
    - Confidence-weighted voting
    - Source prioritization (attachment vs body)
    - Pattern validation
    - Historical data comparison
    """

    def __init__(
        self,
        use_llm: bool = True,
        use_ocr: bool = False,
        use_vision: bool = True,
        results_csv_path: Optional[Path] = None,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ):
        """Initialize ensemble parser.

        Args:
            use_llm: Include LLM body parser
            use_ocr: Include OCR attachment parser
            use_vision: Include vision attachment parser
            results_csv_path: Path to results.csv for historical validation
            api_key: OpenAI API key for description combination (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use for description combination
        """
        super().__init__(name="Ensemble-Parser")

        # Initialize OpenAI client for description combination
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
            self.model = model
        else:
            self.client = None
            self.logger.warning("No OpenAI API key found - description combination will be disabled")

        self.parsers = []

        # Initialize selected parsers
        if use_llm:
            try:
                self.parsers.append(("LLM", LLMBodyParser()))
                self.logger.info("Added LLM parser to ensemble")
            except Exception as e:
                self.logger.warning(f"Failed to initialize LLM parser: {e}")

        if use_ocr:
            try:
                self.parsers.append(("OCR", OCRAttachmentParser()))
                self.logger.info("Added OCR parser to ensemble")
            except Exception as e:
                self.logger.warning(f"Failed to initialize OCR parser: {e}")

        if use_vision:
            try:
                self.parsers.append(("Vision", LayoutLLMParser()))
                self.logger.info("Added Vision parser to ensemble")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Vision parser: {e}")

        # Load historical data if provided
        self.historical_data = None
        if results_csv_path and results_csv_path.exists():
            try:
                self.historical_data = pd.read_csv(results_csv_path)
                self.logger.info(f"Loaded {len(self.historical_data)} historical records")
            except Exception as e:
                self.logger.warning(f"Failed to load historical data: {e}")

    def _majority_vote(self, values: List[Optional[float]]) -> Optional[float]:
        """Select value with most votes.

        Args:
            values: List of values from different parsers

        Returns:
            Most common value or None
        """
        # Filter out None values
        valid_values = [v for v in values if v is not None]

        if not valid_values:
            return None

        # Count occurrences
        counter = Counter(valid_values)
        most_common = counter.most_common(1)[0]

        # Only return if it has clear majority (>50%)
        if most_common[1] > len(valid_values) / 2:
            return most_common[0]

        return None

    def _fuzzy_consensus(
        self, values: List[Optional[float]], tolerance: float = 0.5
    ) -> Optional[float]:
        """Find consensus among similar values.

        Uses fuzzy matching to group similar EBITDA values.

        Args:
            values: List of EBITDA values
            tolerance: Tolerance for fuzzy matching (in millions)

        Returns:
            Consensus value (average of cluster) or None
        """
        valid_values = [v for v in values if v is not None]

        if not valid_values:
            return None

        # Group similar values
        clusters = []
        for value in valid_values:
            # Find if value belongs to existing cluster
            found_cluster = False
            for cluster in clusters:
                if fuzzy_match_ebitda(value, cluster[0], tolerance):
                    cluster.append(value)
                    found_cluster = True
                    break

            if not found_cluster:
                clusters.append([value])

        # Find largest cluster
        largest_cluster = max(clusters, key=len)

        # Return average of largest cluster if it has majority
        if len(largest_cluster) > len(valid_values) / 2:
            return sum(largest_cluster) / len(largest_cluster)

        return None

    def _combine_descriptions(self, results: List[Tuple[str, ParserResult]]) -> Optional[str]:
        """Combine descriptions from multiple parsers using OpenAI.
        
        Collects all descriptions from different parsers and asks OpenAI to synthesize
        the best description, noting that some may be incorrect.
        
        Args:
            results: List of (parser_name, result) tuples
            
        Returns:
            Combined description or None if no descriptions found
        """
        # Collect all descriptions with their sources
        descriptions = []
        for name, result in results:
            if result and result.opportunity:
                opp = result.opportunity
                if hasattr(opp, "description") and opp.description:
                    source_type = "attachment" if result.extraction_source == "attachment" else "body"
                    descriptions.append({
                        "text": opp.description,
                        "source": name,
                        "type": source_type
                    })
        
        if not descriptions:
            return None
        
        # If only one description, return it
        if len(descriptions) == 1:
            desc = descriptions[0]
            self.logger.info(f"Using single description from {desc['source']} ({desc['type']}): {desc['text']}")
            return desc['text']
        
        # Multiple descriptions - combine using OpenAI
        if not self.client:
            # Fallback: use attachment description if available, else first one
            for desc in descriptions:
                if desc['type'] == 'attachment':
                    self.logger.info(f"Using description from {desc['source']} (attachment, no OpenAI): {desc['text']}")
                    return desc['text']
            self.logger.info(f"Using first description (no OpenAI): {descriptions[0]['text']}")
            return descriptions[0]['text']
        
        # Build prompt with all descriptions
        desc_list = "\n".join([
            f"- {desc['text']} (from {desc['source']}, {desc['type']})"
            for desc in descriptions
        ])
        
        prompt = f"""You are helping to extract a business description for an investment opportunity.

Multiple parsers have extracted different descriptions from the same document/email. Some may be incorrect, incomplete, or less accurate than others.

DESCRIPTIONS FOUND:
{desc_list}

TASK:
Combine these descriptions into ONE final description that:
1. Is EXACTLY 2-5 words (count your words!)
2. Best describes the core business/company
3. Uses the most accurate and complete information
4. Ignores incorrect or less relevant descriptions

EXAMPLES:
- "Leading Canadian Footwear Brand" (4 words)
- "Regional Distribution Business" (3 words)
- "Industrial Products Company" (3 words)
- "Fiberglass Manufacturing Business" (3 words)

If descriptions mention "opportunity to acquire" or similar investment language, extract just the business description part.

Return ONLY the final description (2-5 words), nothing else."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise data extraction assistant. Return only the description text, no additional explanation."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=50,
            )
            
            combined_desc = response.choices[0].message.content.strip()
            
            # Validate word count
            word_count = len(combined_desc.split())
            if word_count < 2 or word_count > 5:
                self.logger.warning(f"Combined description '{combined_desc}' has {word_count} words (should be 2-5)")
                # Try to fix: if too long, take first 5 words
                words = combined_desc.split()
                if len(words) > 5:
                    combined_desc = " ".join(words[:5])
                    self.logger.info(f"Truncated combined description to: {combined_desc}")
            
            self.logger.info(f"✓ Combined {len(descriptions)} descriptions into: {combined_desc} ({len(combined_desc.split())} words)")
            return combined_desc
            
        except Exception as e:
            self.logger.error(f"Failed to combine descriptions with OpenAI: {e}")
            # Fallback: use attachment description if available, else first one
            for desc in descriptions:
                if desc['type'] == 'attachment':
                    self.logger.info(f"Using description from {desc['source']} (attachment, fallback): {desc['text']}")
                    return desc['text']
            self.logger.info(f"Using first description (fallback): {descriptions[0]['text']}")
            return descriptions[0]['text']

    def _source_prioritized(self, results: List[Tuple[str, ParserResult]]) -> Optional[float]:
        """Prioritize values by source.

        Priority order:
        1. Attachment-based parsers (more detailed documents)
        2. Body-based parsers (email text)

        Args:
            results: List of (parser_name, result) tuples

        Returns:
            Prioritized EBITDA value
        """
        # First try attachment parsers
        for name, result in results:
            if result.extraction_source == "attachment":
                if result.opportunity.ebitda_millions is not None:
                    self.logger.info(f"Using attachment source ({name})")
                    return result.opportunity.ebitda_millions

        # Fall back to body parsers
        for name, result in results:
            if result.extraction_source == "body":
                if result.opportunity.ebitda_millions is not None:
                    self.logger.info(f"Using body source ({name})")
                    return result.opportunity.ebitda_millions

        return None

    def _select_best_field(
        self, results: List[Tuple[str, ParserResult]], options_field: str, fallback_field: str
    ) -> Optional[str]:
        """Select best value for a field using confidence-based selection.

        Combines:
        - Parser method confidence (LLM > Vision > NER > OCR)
        - Extraction confidence (from FieldOption)

        Args:
            results: List of (parser_name, result) tuples
            options_field: Name of the options field (e.g., "location_options")
            fallback_field: Name of the fallback field (e.g., "hq_location")

        Returns:
            Best value or None
        """
        # Define parser confidence weights
        parser_weights = {
            "LLM": 1.0,
            "Vision": 0.9,
            "NER": 0.7,
            "OCR": 0.5,
        }

        source_weights = {
            "attachment": 1.2,
            "body": 1.0,
            "both": 1.1,
        }

        best_value = None
        best_combined_score = 0.0
        best_source = ""

        for name, result in results:
            # Get parser method confidence
            method_confidence = parser_weights.get(name, 0.5)
            method_confidence *= source_weights.get(result.extraction_source, 1.0)

            # Check options field
            options = getattr(result.opportunity, options_field, [])
            for option in options:
                # Combined score: method confidence × extraction confidence
                combined_score = method_confidence * option.confidence

                if combined_score > best_combined_score:
                    best_combined_score = combined_score
                    best_value = option.value
                    best_source = f"{name} (method: {method_confidence:.2f}, extraction: {option.confidence:.2f}, combined: {combined_score:.2f})"

        # Fallback to simple field if no options
        # Prioritize attachment parsers (OCR + LLM, Layout LLM) over body parsers
        if best_value is None:
            # First try attachment parsers (they often have better data)
            for name, result in results:
                fallback_value = getattr(result.opportunity, fallback_field, None)
                if fallback_value and result.extraction_source == "attachment":
                    best_value = fallback_value
                    best_source = f"{name} (attachment fallback)"
                    break
            
            # Then try body parsers if attachment parsers didn't have it
            if best_value is None:
                for name, result in results:
                    fallback_value = getattr(result.opportunity, fallback_field, None)
                    if fallback_value and result.extraction_source == "body":
                        best_value = fallback_value
                        best_source = f"{name} (body fallback)"
                        break

            # Last resort: any non-None value from any parser
            if best_value is None:
                for name, result in results:
                    fallback_value = getattr(result.opportunity, fallback_field, None)
                    if fallback_value:
                        best_value = fallback_value
                        best_source = f"{name} (last resort)"
                        break

        if best_value:
            self.logger.info(f"Selected {options_field}: {best_value} using {best_source}")

        return best_value

    def _confidence_weighted(
        self, results: List[Tuple[str, ParserResult]]
    ) -> Tuple[Optional[float], str]:
        """Select value with highest confidence score.

        Assigns confidence scores based on:
        - Parser type (LLM > Vision > NER > OCR)
        - Extraction source (attachment > body)
        - Has raw text evidence

        Args:
            results: List of (parser_name, result) tuples

        Returns:
            Tuple of (selected_ebitda_value, selection_reason)
        """
        # Define confidence weights
        parser_weights = {
            "LLM": 1.0,
            "Vision": 0.9,
            "NER": 0.7,
            "OCR": 0.5,
        }

        source_weights = {
            "attachment": 1.2,
            "body": 1.0,
            "both": 1.1,
        }

        best_value = None
        best_score = 0.0
        best_source = ""

        for name, result in results:
            ebitda = result.opportunity.ebitda_millions

            if ebitda is None:
                continue

            # Calculate confidence score
            score = parser_weights.get(name, 0.5)
            score *= source_weights.get(result.extraction_source, 1.0)

            # Bonus for having raw text (higher confidence)
            if result.opportunity.raw_ebitda_text:
                score *= 1.1

            if score > best_score:
                best_score = score
                best_value = ebitda
                best_source = f"{name} (score: {score:.2f})"

        return best_value, best_source

    def _validate_against_historical(
        self, company_name: Optional[str], ebitda_values: List[Optional[float]]
    ) -> Optional[float]:
        """Validate against historical data (results.csv).

        Args:
            company_name: Company or project name
            ebitda_values: List of candidate EBITDA values

        Returns:
            EBITDA value closest to historical record
        """
        if self.historical_data is None or not company_name:
            return None

        # Search for company in historical data
        matches = self.historical_data[
            self.historical_data["Company / Project Name"].str.contains(
                company_name, case=False, na=False
            )
        ]

        if matches.empty:
            return None

        historical_ebitda = matches.iloc[0]["LTM EBITDA ($M)"]

        # Parse historical EBITDA
        try:
            if isinstance(historical_ebitda, str):
                if historical_ebitda == "n.a.":
                    return None
                historical_ebitda = float(historical_ebitda.replace("$", "").replace(",", ""))
            else:
                historical_ebitda = float(historical_ebitda)
        except (ValueError, TypeError):
            return None

        # Find closest match
        valid_values = [v for v in ebitda_values if v is not None]
        if not valid_values:
            return None

        closest = min(valid_values, key=lambda x: abs(x - historical_ebitda))

        self.logger.info(
            f"Historical EBITDA: ${historical_ebitda}M, " f"Closest match: ${closest}M"
        )

        return closest

    def _combine_results(
        self, results: List[Tuple[str, ParserResult]], strategy: str = "all"
    ) -> InvestmentOpportunity:
        """Combine results from multiple parsers using specified strategy.

        IMPORTANT: Does NOT average values. Selects the best value based on confidence.

        Args:
            results: List of (parser_name, result) tuples
            strategy: Combining strategy ('majority', 'weighted', 'prioritized', 'all')

        Returns:
            Combined InvestmentOpportunity
        """
        # Extract all opportunities
        opportunities = [r[1].opportunity for r in results]

        # Combine EBITDA values using different strategies
        ebitda_values = [o.ebitda_millions for o in opportunities]
        company_names = [o.company_name for o in opportunities if o.company_name]

        final_ebitda = None
        tie_break_method = "unknown"

        if strategy == "all" or strategy == "fuzzy":
            # Try fuzzy consensus first - if values are close, they're the same
            consensus = self._fuzzy_consensus(ebitda_values, tolerance=0.001)
            if consensus:
                final_ebitda = consensus
                tie_break_method = "fuzzy_consensus (values within ±$1K)"

        if final_ebitda is None and (strategy == "all" or strategy == "majority"):
            # Try majority vote - if multiple parsers agree exactly
            final_ebitda = self._majority_vote(ebitda_values)
            if final_ebitda:
                tie_break_method = "majority_vote"

        if final_ebitda is None and (strategy == "all" or strategy == "weighted"):
            # Select value with highest confidence (DON'T AVERAGE)
            final_ebitda, reason = self._confidence_weighted(results)
            if final_ebitda:
                tie_break_method = f"confidence_selection: {reason}"

        if final_ebitda is None and (strategy == "all" or strategy == "prioritized"):
            # Try source prioritization
            final_ebitda = self._source_prioritized(results)
            if final_ebitda:
                tie_break_method = "source_prioritized (attachment > body)"

        if final_ebitda is None and (strategy == "all" or strategy == "historical"):
            # Try historical validation
            company_name = company_names[0] if company_names else None
            final_ebitda = self._validate_against_historical(company_name, ebitda_values)
            if final_ebitda:
                tie_break_method = "historical_validation"

        # If still no EBITDA, take first non-None value
        if final_ebitda is None:
            for ebitda in ebitda_values:
                if ebitda is not None:
                    final_ebitda = ebitda
                    tie_break_method = "first_available"
                    break

        # Combine all fields using confidence-based selection
        best_location = self._select_best_field(results, "location_options", "hq_location")
        best_sector = self._select_best_field(results, "sector_options", "sector")
        best_company = self._select_best_field(results, "company_options", "company_name")
        
        # Validate sector - must be in VALID_SECTORS
        from email_parser.base import VALID_SECTORS
        if best_sector and best_sector not in VALID_SECTORS:
            self.logger.warning(f"Invalid sector '{best_sector}' from ensemble, defaulting to 'Other'")
            best_sector = "Other"

        # Combine descriptions from all parsers using OpenAI
        description = self._combine_descriptions(results)

        combined = InvestmentOpportunity(
            source_domain=next((o.source_domain for o in opportunities if o.source_domain), None),
            recipient=next((o.recipient for o in opportunities if o.recipient), None),
            hq_location=best_location,
            ebitda_millions=final_ebitda,
            date=next((o.date for o in opportunities if o.date), None),
            company_name=best_company,
            sector=best_sector,
            description=description,
            raw_ebitda_text=f"[{tie_break_method}]",
        )

        self.logger.info(f"Selected EBITDA: ${final_ebitda}M using: {tie_break_method}")

        return combined

    def _run_single_parser(
        self, name: str, parser: BaseParser, email_data: EmailData
    ) -> Optional[Tuple[str, ParserResult]]:
        """Run a single parser (for parallel execution).

        Args:
            name: Parser name
            parser: Parser instance
            email_data: Email data to parse

        Returns:
            Tuple of (name, result) or None if failed
        """
        try:
            self.logger.info(f"Running {name} parser...")
            opportunity = parser.parse_data(email_data)

            # Create a mock result for combining
            result = ParserResult(
                opportunity=opportunity,
                parser_name=name,
                extraction_source=getattr(parser, "extraction_source", "body"),
                processing_time_seconds=0.0,
            )

            return (name, result)

        except Exception as e:
            self.logger.error(f"{name} parser failed: {e}")
            return None

    def parse_data(self, email_data: EmailData, parallel: bool = True) -> InvestmentOpportunity:
        """Parse email data using ensemble of parsers.

        Args:
            email_data: Extracted email data
            parallel: If True, run parsers in parallel (default: True)

        Returns:
            Combined InvestmentOpportunity
        """
        results = []

        if parallel and len(self.parsers) > 1:
            # Run parsers in parallel using ThreadPoolExecutor
            self.logger.info(f"Running {len(self.parsers)} parsers in parallel...")

            with ThreadPoolExecutor(max_workers=len(self.parsers)) as executor:
                # Submit all parser tasks
                future_to_parser = {
                    executor.submit(self._run_single_parser, name, parser, email_data): name
                    for name, parser in self.parsers
                }

                # Collect results as they complete
                for future in as_completed(future_to_parser):
                    result = future.result()
                    if result is not None:
                        results.append(result)

        else:
            # Run parsers sequentially (original behavior)
            self.logger.info("Running parsers sequentially...")
            for name, parser in self.parsers:
                result = self._run_single_parser(name, parser, email_data)
                if result is not None:
                    results.append(result)

        # Combine results
        return self._combine_results(results, strategy="all")
        return self._combine_results(results, strategy="all")
