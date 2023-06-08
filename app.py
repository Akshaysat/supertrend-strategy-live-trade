import streamlit as st
import json
import time
import pandas as pd
import datetime as dt
from pymongo import MongoClient, DESCENDING
import requests
import plotly.express as px
import plotly.graph_objects as go


def color_survived(val):
    if val > 0:
        color = "#7FFF00"
    elif val < 0:
        color = "#dc143c"
    return f"color: {color}"


st.markdown(
    "<h2 style='text-align: center; color: white;'>Supertrend Strategy - Live Trades</h2>",
    unsafe_allow_html=True,
)

st.write("-----")
strategy_name = "STS (SuperTrend Strategy)".lower()

strategy_db_name = strategy_name.split(" ")[0]

# connect to the database
mongo = MongoClient(st.secrets["mongo_db"]["mongo_url"])
mydb = mongo["test"]
coll = mydb[f"systematic-strategy-{strategy_db_name}"]

df = pd.DataFrame(
    list(coll.find()),
    columns=[
        "trade_date",
        "strike",
        "entry_price",
        "sl_price",
        "qty",
        "entry_time",
        "exit_price",
        "pnl",
        "exit_time",
        "exit_type",
        "pnl_movement",
        "trade_type",
    ],
)
df = df.set_index("strike")



# Calculate Net PNL after slippages

df["entry_price_with_slippage"] = df.apply(
    lambda x: round(x["entry_price"] * 0.98, 2)
    if x["trade_type"] == "SHORT"
    else round(x["entry_price"] * 1.02, 2),
    axis=1,
)

if strategy_db_name == "macd":
    
    df["net_pnl"] = df.apply(
        lambda x: round(x["entry_price_with_slippage"] - x["entry_price"] + x["pnl"], 2),
        axis=1,
    )

else:

    df["net_pnl"] = df.apply(
        lambda x: round(x["entry_price_with_slippage"] - x["exit_price"], 2)
        if x["trade_type"] == "SHORT"
        else round(x["exit_price"] - x["entry_price_with_slippage"], 2),
        axis=1,
    )

# What do you want to analyze?
feature = st.radio(
    "What do you want to analyze?",
    ("Analyze Strategy Statistics", "Analyze a particular day's trade"),
)

if feature == "Analyze a particular day's trade":
    # Datewise PNL
    st.write("----")
    selected_date = str(st.date_input("Select trade date:"))
    st.write("-----")

    df_selected_date = df[df["trade_date"] == selected_date]

    if df_selected_date.shape[0] == 0:
        st.info(f"No Trade on {selected_date}")
    else:
        net_pnl = round(df_selected_date["net_pnl"].sum(), 2)
        if net_pnl >= 0:
            st.success(f"Net PNL (in pts.): \n {net_pnl}")
        else:
            st.error(f"Net PNL (in pts.): \n {net_pnl}")

    st.write("")

    for i in df_selected_date.index:
        
        try:
            st.table(
                df_selected_date.loc[
                    i,
                    [
                        "entry_price",
                        "exit_price",
                        "entry_time",
                        "exit_time",
                        "sl_price",
                        "exit_type",
                        "trade_type",
                        "entry_price_with_slippage",
                        "net_pnl",
                    ],
                ].T
            )

            pnl_movement_link = df_selected_date.loc[i]["pnl_movement"]

            st.image(
                pnl_movement_link,
                caption="PNL Movement",
            )

            st.write("---")
        except:
            #st.info(f'PNL Chart not available for {i}')
            st.write("---")
            continue

else:

    # st.write(df)
    
    if strategy_db_name == "macd":
        df = df.reset_index()
        stats_df = df[["trade_date","strike","net_pnl"]]
        stats_df["trade_no"] = stats_df.reset_index().rename(columns={'index': 'trade_no'})['trade_no'] + 1
    else:
        stats_df = df[["trade_date", "net_pnl"]].groupby(["trade_date"], sort=False).sum()
        stats_df.reset_index(inplace=True)
    
    
    stats_df = stats_df.sort_values(by = "trade_date")

    # set inital streak values
    stats_df["loss_streak"] = 0
    stats_df["win_streak"] = 0

    if stats_df["net_pnl"][0] > 0:
        stats_df["loss_streak"][0] = 0
        stats_df["win_streak"][0] = 1

    else:
        stats_df["loss_streak"][0] = 1
        stats_df["win_streak"][0] = 0

    # find winning and losing streaks
    for i in range(1, stats_df.shape[0]):

        if stats_df["net_pnl"][i] > 0:
            stats_df["loss_streak"][i] = 0
            stats_df["win_streak"][i] = stats_df["win_streak"][i - 1] + 1

        else:
            stats_df["win_streak"][i] = 0
            stats_df["loss_streak"][i] = stats_df["loss_streak"][i - 1] + 1

    # cumulative PNL
    stats_df["cum_pnl"] = stats_df["net_pnl"].cumsum()

    # Create Drawdown column
    stats_df["drawdown"] = 0
    for i in range(0, stats_df.shape[0]):

        if i == 0:
            if stats_df["net_pnl"].iloc[i] > 0:
                stats_df["drawdown"].iloc[i] = 0
            else:
                stats_df["drawdown"].iloc[i] = stats_df["net_pnl"].iloc[i]
        else:
            if stats_df["net_pnl"].iloc[i] + stats_df["drawdown"].iloc[i - 1] > 0:
                stats_df["drawdown"].iloc[i] = 0
            else:
                stats_df["drawdown"].iloc[i] = (
                    stats_df["net_pnl"].iloc[i] + stats_df["drawdown"].iloc[i - 1]
                )


    # create monthly data
    stats_df["month"] = pd.DatetimeIndex(stats_df["trade_date"]).month
    stats_df["year"] = pd.DatetimeIndex(stats_df["trade_date"]).year
    stats_df["month"] = (
        pd.to_datetime(stats_df["month"], format="%m").dt.month_name().str.slice(stop=3)
    )
    stats_df["week_day"] = (
        stats_df["trade_date"]
        .apply(lambda x: dt.datetime.strptime(x, "%Y-%m-%d"))
        .dt.day_name()
    )
    stats_df["month_year"] = (
        stats_df["month"] + " " + stats_df["year"].astype(str)
    ).str.slice(stop=11)
    # Dataframe for monthly returns
    stats_df_month = stats_df.groupby(["month_year"], sort=False).sum()
    stats_df_month = stats_df_month.reset_index()

    stats_df_weekday = stats_df.groupby(["week_day"], sort=False).sum()
    stats_df_weekday = stats_df_weekday.reset_index()

    cats = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    stats_df_weekday["week_day"] = pd.Categorical(
        stats_df_weekday["week_day"], categories=cats, ordered=True
    )

    stats_df_weekday = stats_df_weekday.sort_values("week_day")

    # Calculate Statistics
    total_days = len(stats_df)
    winning_days = (stats_df["net_pnl"] > 0).sum()
    losing_days = (stats_df["net_pnl"] < 0).sum()

    win_ratio = round((winning_days / total_days) * 100, 2)
    max_profit = round(stats_df["net_pnl"].max(), 2)
    max_loss = round(stats_df["net_pnl"].min(), 2)
    max_drawdown = round(stats_df["drawdown"].min(), 2)
    max_winning_streak = max(stats_df["win_streak"])
    max_losing_streak = max(stats_df["loss_streak"])
    avg_profit_on_win_days = round(
        stats_df[stats_df["net_pnl"] > 0]["net_pnl"].sum()
        / len(stats_df[stats_df["net_pnl"] >= 0]),
        2,
    )
    avg_loss_on_loss_days = round(
        stats_df[stats_df["net_pnl"] < 0]["net_pnl"].sum()
        / len(stats_df[stats_df["net_pnl"] < 0]),
        2,
    )
    avg_profit_per_day = round(stats_df["net_pnl"].sum() / len(stats_df), 2)
    expectancy = round(
        (avg_profit_on_win_days * win_ratio + avg_loss_on_loss_days * (100 - win_ratio))
        * 0.01,
        2,
    )
    net_profit = round(stats_df["cum_pnl"].iloc[-1], 2)

    KPI = {
        "Total days": total_days,
        "Winning days": winning_days,
        "Losing days": losing_days,
        "Max Profit": max_profit,
        "Max Loss": max_loss,
        "Max Winning Streak": max_winning_streak,
        "Max Losing Streak": max_losing_streak,
        "Max Drawdown": max_drawdown,
        "Average Profit on win days": avg_profit_on_win_days,
        "Average Loss on loss days": avg_loss_on_loss_days,
        "System Expectancy": expectancy,
    }
    strategy_stats = pd.DataFrame(KPI.values(), index=KPI.keys(), columns=[" "]).astype(
        float
    )

    # Show Statistics
    st.write("-----")
    col1, col2, col3 = st.columns(3)
    col1.metric(label="Win %", value=str(win_ratio) + " %")
    col2.metric(label="Net Profit (in pts.)", value=str(round(net_profit, 2)))
    col3.metric(
        label="Avg. daily profit (in pts.)", value=str(round(avg_profit_per_day, 2))
    )
    st.write("-----")
    st.subheader("Strategy Statistics")
    # st.table(strategy_stats.style.format(precision=2))
    st._legacy_table(strategy_stats)
    st.write("-----")

    # Show equity curve
    st.subheader("Equity Curve")
    if strategy_db_name == "macd":
        fig_pnl = px.line(stats_df, x="trade_no", y="cum_pnl", width=800, height=500)
    else:
        fig_pnl = px.line(stats_df, x="trade_date", y="cum_pnl", width=800, height=500)
        
    fig_pnl.update_xaxes(showgrid=False)  # turn off x-axis gridlines
    fig_pnl.update_yaxes(showgrid=True)  # turn off y-axis gridlines
    st.plotly_chart(fig_pnl)
    st.write("-----")
    

    # show drawdown curve
    st.subheader("Drawdown Curve")
    if strategy_db_name == "macd":
        fig_dd = px.line(stats_df, x="trade_no", y="drawdown", width=800, height=500)
    else:
        fig_dd = px.line(stats_df, x="trade_date", y="drawdown", width=800, height=500)
    fig_dd.update_xaxes(showgrid=False)  # turn off x-axis gridlines
    fig_dd.update_yaxes(showgrid=True)  # turn off y-axis gridlines
    st.plotly_chart(fig_dd)
    st.write("-----")

    # Month-wise PNL
    st.header("Month-wise PNL")

    stats_df_month["net_pnl"] = stats_df_month["net_pnl"].round(2)

    stats_df_month["color"] = [
        "lightgreen" if x > 0 else "lightcoral" for x in stats_df_month["net_pnl"]
    ]

    fig_stats_month = px.bar(
        stats_df_month,
        x="month_year",
        y="net_pnl",
        color="color",
        color_discrete_map="identity",
    )

    fig_stats_month.update_xaxes(showgrid=False)  # turn off x-axis gridlines
    fig_stats_month.update_yaxes(showgrid=False)  # turn off y-axis gridlines

    st.plotly_chart(fig_stats_month)
    st.write("-----")

    # Week-wise PNL
    st.header("Weekday-wise PNL")
    # stats_df_month = stats_df_month.style.format(precision=2)

    stats_df_weekday["net_pnl"] = stats_df_weekday["net_pnl"].round(2)

    stats_df_weekday["color"] = [
        "lightgreen" if x > 0 else "lightcoral" for x in stats_df_weekday["net_pnl"]
    ]

    fig_stats_weekday = px.bar(
        stats_df_weekday,
        x="week_day",
        y="net_pnl",
        color="color",
        color_discrete_map="identity",
    )

    fig_stats_weekday.update_xaxes(showgrid=False)  # turn off x-axis gridlines
    fig_stats_weekday.update_yaxes(showgrid=False)  # turn off y-axis gridlines

    st.plotly_chart(fig_stats_weekday)
