import pandas as pd
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded


@shared_task(bind=True, ignore_result=False)
def conditional_demographic_disparity(self: Task, target, sensitive, accepted_value):
    """
    Calculate the demographic disparity metric for multiple target and sensitive groups.

    Parameters:
    target (list or array): The target feature.
    sensitive (list or array): The sensitive attribute.
    accepted_value: The value in the target feature representing an accepted outcome.

    Returns:
    pd.DataFrame: A DataFrame containing the demographic disparity results for each sensitive group.
    """
    try:
        accepted_value = type(target[0])(
            accepted_value
        )  # cast accepted_value to the same type as target elements

        # Create a DataFrame from the input lists
        df = pd.DataFrame({"target": target, "sensitive": sensitive})
        print(df)
        # Convert target to binary (1 for accepted, 0 for rejected)
        df["target_binary"] = df["target"].apply(
            lambda x: 1 if x == accepted_value else 0
        )
        print(df["target_binary"])
        # Calculate counts for each group and target combination
        group_counts = (
            df.groupby(["sensitive", "target_binary"]).size().unstack(fill_value=0)
        )

        # Calculate the total numbers of rejected and accepted outcomes
        total_rejected = group_counts[0].sum()
        total_accepted = group_counts[
            1
        ].sum()  # if there are no accepted values, this column will not exist and an error will be raised
        # Initialize a list to store results
        results = {}

        # Calculate the proportions and disparities for each group
        for group in group_counts.index:
            proportion_rejected = (
                group_counts.loc[group, 0] / total_rejected if total_rejected > 0 else 0
            )
            proportion_accepted = (
                group_counts.loc[group, 1] / total_accepted if total_accepted > 0 else 0
            )

            # Determine demographic disparity
            disparity = proportion_rejected > proportion_accepted

            # Add results to the dictionary
            results[group] = {
                f"proportion_{accepted_value}": proportion_rejected,
                f"proportion_not_{accepted_value}": proportion_accepted,
                "disparity": str(disparity),
            }

        # Convert results to a DataFrame
        # results_df = pd.DataFrame(results)

        return {"Disparities": results}
    except SoftTimeLimitExceeded:
        raise Exception("Duplicity task timed out.")
