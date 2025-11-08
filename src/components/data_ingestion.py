import pandas as pd
import xml.etree.ElementTree as ET
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AppleHealthXMLParser:
    def __init__(self, xml_path: str):
        self.xml_path = xml_path
        if not os.path.exists(xml_path):
            raise FileNotFoundError(f"XML file not found at {xml_path}")
        self.tree = None
        self.root = None
        self.df_records = None
        self.df_workouts = None
        self.df_daily = None
        self.df_pivoted = None

    def parse(self) -> pd.DataFrame:
        """Parse XML and return processed dataframe"""
        logging.info(f"Parsing XML from {self.xml_path}")
        
        self.tree = ET.parse(self.xml_path)
        self.root = self.tree.getroot()

        records = []
        for record in self.root.findall('.//Record'):
            try:
                record_data = {
                    'type': record.get('type'),
                    'sourceName': record.get('sourceName'),
                    'unit': record.get('unit'),
                    'value': float(record.get('value', 0)),
                    'startDate': pd.to_datetime(record.get('startDate')),  # Fixed typo
                    'endDate': pd.to_datetime(record.get('endDate'))  # Fixed typo
                }
                records.append(record_data)  # Fixed: was record.append
            except Exception as e:
                logging.warning(f"Skipping record due to error: {e}")
                continue

        self.df_records = pd.DataFrame(records)
        logging.info(f"Parsed {len(self.df_records)} health records")

        workouts = []
        for workout in self.root.findall('.//Workout'):
            try:
                workout_data = {
                    'workoutActivityType': workout.get('workoutActivityType'),
                    'duration': float(workout.get('duration', 0)),
                    'totalDistance': float(workout.get('totalDistance', 0)),
                    'totalEnergyBurned': float(workout.get('totalEnergyBurned', 0)),
                    'startDate': pd.to_datetime(workout.get('startDate')),
                    'endDate': pd.to_datetime(workout.get('endDate'))
                }
                workouts.append(workout_data)
            except Exception as e:
                logging.warning(f"Error parsing workout: {e}")
                continue
        
        self.df_workouts = pd.DataFrame(workouts)
        logging.info(f"Parsed {len(self.df_workouts)} workout records")
        
        return self.df_records

    def aggregate_daily_metrics(self) -> pd.DataFrame:  # Fixed typo in method name
        """Aggregate daily metrics from health records"""
        if self.df_records is None or self.df_records.empty:
            raise ValueError("Dataframe is empty. Please run parse() first.")

        metric_types = {
            'HKQuantityTypeIdentifierHeartRate': ('heart_rate', 'mean'),
            'HKQuantityTypeIdentifierHeartRateVariabilitySDNN': ('hrv', 'mean'),
            'HKQuantityTypeIdentifierStepCount': ('steps', 'sum'),
            'HKQuantityTypeIdentifierActiveEnergyBurned': ('active_calories', 'sum'),
            'HKQuantityTypeIdentifierRestingHeartRate': ('resting_hr', 'mean'),
            'HKQuantityTypeIdentifierWalkingHeartRateAverage': ('walking_hr', 'mean'),
            'HKQuantityTypeIdentifierAppleExerciseTime': ('exercise_minutes', 'sum'),
            'HKQuantityTypeIdentifierAppleStandHour': ('stand_hours', 'sum'),
            'HKQuantityTypeIdentifierDistanceWalkingRunning': ('distance', 'sum'),
            'HKQuantityTypeIdentifierFlightsClimbed': ('flights_climbed', 'sum')
        }
        
        # Extract date from startDate
        self.df_records['date'] = self.df_records['startDate'].dt.date
        
        daily_aggregations = {}
        
        for record_type, (column_name, agg_func) in metric_types.items():
            filtered_df = self.df_records[self.df_records['type'] == record_type]
            if not filtered_df.empty:
                if agg_func == 'mean':
                    daily_aggregations[column_name] = filtered_df.groupby('date')['value'].mean()
                elif agg_func == 'sum':
                    daily_aggregations[column_name] = filtered_df.groupby('date')['value'].sum()
        
        # Combine all metrics into a single dataframe
        if daily_aggregations:
            self.df_daily = pd.DataFrame(daily_aggregations)
            self.df_daily = self.df_daily.reset_index()
            self.df_daily = self.df_daily.sort_values('date')
            logging.info(f"Created daily aggregation with {len(self.df_daily)} days")
        else:
            self.df_daily = pd.DataFrame()
            logging.warning("No metrics found for daily aggregation")
        
        return self.df_daily

    def create_pivoted_dataframe(self) -> pd.DataFrame:
        """
        Create a pivoted dataframe with record types as columns and sequential values.
        Each row represents a timestamp, and columns contain values for each record type.
        """
        if self.df_records is None or self.df_records.empty:
            raise ValueError("Dataframe is empty. Please run parse() first.")
        
        # Sort records by startDate to maintain sequential order
        df_sorted = self.df_records.sort_values('startDate').copy()
        
        # Create a sequential index for each record type
        df_sorted['sequence'] = df_sorted.groupby('type').cumcount()
        
        # Get simplified type names (remove HKQuantityTypeIdentifier prefix for readability)
        df_sorted['type_simplified'] = df_sorted['type'].str.replace('HKQuantityTypeIdentifier', '')
        
        # Pivot the dataframe to have record types as columns
        self.df_pivoted = df_sorted.pivot_table(
            index='sequence',
            columns='type_simplified',
            values='value',
            aggfunc='first'  # Use first value if there are duplicates
        )
        
        # Reset index to make sequence a regular column
        self.df_pivoted = self.df_pivoted.reset_index()
        
        logging.info(f"Created pivoted dataframe with {len(self.df_pivoted)} rows and {len(self.df_pivoted.columns)-1} record types")
        
        return self.df_pivoted

    def create_time_series_dataframe(self) -> pd.DataFrame:
        """
        Create a time-series dataframe with timestamps and record types as columns.
        Each row represents a unique timestamp with all available measurements.
        """
        if self.df_records is None or self.df_records.empty:
            raise ValueError("Dataframe is empty. Please run parse() first.")
        
        # Sort by startDate
        df_sorted = self.df_records.sort_values('startDate').copy()
        
        # Simplify type names
        df_sorted['type_simplified'] = df_sorted['type'].str.replace('HKQuantityTypeIdentifier', '')
        
        # Pivot with startDate as index
        df_time_series = df_sorted.pivot_table(
            index='startDate',
            columns='type_simplified',
            values='value',
            aggfunc='mean'  # Average if multiple values at same timestamp
        )
        
        # Reset index to make startDate a regular column
        df_time_series = df_time_series.reset_index()
        df_time_series.rename(columns={'startDate': 'timestamp'}, inplace=True)
        
        logging.info(f"Created time series dataframe with {len(df_time_series)} timestamps")
        
        return df_time_series

    def export_to_csv(self, output_path: str, format_type: str = 'pivoted'):
        """
        Export the parsed data to CSV in the specified format.
        
        Parameters:
        -----------
        output_path : str
            Path where the CSV file will be saved
        format_type : str
            Type of format for the CSV:
            - 'pivoted': Sequential values with record types as columns
            - 'time_series': Time-based with timestamps and record types as columns
            - 'daily': Daily aggregated metrics
            - 'raw': Raw parsed records
        """
        if format_type == 'pivoted':
            if self.df_pivoted is None:
                self.create_pivoted_dataframe()
            df_to_export = self.df_pivoted
        elif format_type == 'time_series':
            df_to_export = self.create_time_series_dataframe()
        elif format_type == 'daily':
            if self.df_daily is None:
                self.aggregate_daily_metrics()
            df_to_export = self.df_daily
        elif format_type == 'raw':
            df_to_export = self.df_records
        else:
            raise ValueError(f"Invalid format_type: {format_type}. Choose from 'pivoted', 'time_series', 'daily', or 'raw'")
        
        if df_to_export is not None and not df_to_export.empty:
            df_to_export.to_csv(output_path, index=False)
            logging.info(f"Exported {len(df_to_export)} rows to {output_path}")
        else:
            logging.warning("No data to export")

    def get_record_type_summary(self) -> pd.DataFrame:
        """Get a summary of all record types in the data"""
        if self.df_records is None or self.df_records.empty:
            raise ValueError("Dataframe is empty. Please run parse() first.")
        
        summary = self.df_records.groupby('type').agg({
            'value': ['count', 'mean', 'min', 'max'],
            'unit': 'first'
        }).round(2)
        
        summary.columns = ['_'.join(col).strip() for col in summary.columns.values]
        summary = summary.reset_index()
        
        return summary


# Example usage
if __name__ == "__main__":
    # Initialize parser
    parser = AppleHealthXMLParser("data/raw/export.xml")  # Replace with your XML file path
    
    try:
        # Parse the XML file
        records_df = parser.parse()
        
        # Create pivoted dataframe with record types as columns
        pivoted_df = parser.create_pivoted_dataframe()
        
        # Export to CSV (this is what you requested - record types as columns)
        parser.export_to_csv("health_data_pivoted.csv", format_type='pivoted')
        
        # You can also export in other formats:
        # Time series format (with timestamps)
        parser.export_to_csv("health_data_time_series.csv", format_type='time_series')
        
        # Daily aggregated metrics
        parser.aggregate_daily_metrics()
        parser.export_to_csv("health_data_daily.csv", format_type='daily')
        
        # Get summary of record types
        summary = parser.get_record_type_summary()
        print("\nRecord Type Summary:")
        print(summary)
        
    except Exception as e:
        logging.error(f"Error processing health data: {e}")