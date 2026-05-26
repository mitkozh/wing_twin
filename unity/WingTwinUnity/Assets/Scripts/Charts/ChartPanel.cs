using UnityEngine;
using UnityEngine.UI;
using XCharts.Runtime;
using System.Collections.Generic;

public class ChartPanel : MonoBehaviour
{
    [Header("Settings")]
    [SerializeField] private int chartCapacity = 300;

    private LineChart strainChart;
    private LineChart damageChart;
    private LineChart stressChart;
    private BarChart rainflowChart;
    private List<BaseChart> charts;
    private int currentIndex = 0;

    private float[] strainBuffer, damageBuffer, stressBuffer;
    private int strainHead, damageHead, stressHead;
    private int strainCount, damageCount, stressCount;

    private float currentYield = 100_000_000f;
    private float maxStrain = 1f, maxDamage = 1f, maxStress = 1f;
    private Font defaultFont;
    private GameObject chartContainer;
    private bool initialized = false;
    private int lastRainflowBinCount = 0;

    void Awake()
    {
        defaultFont = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");

        var panelTransform = transform.Find("Panel");
        if (panelTransform == null)
        {
            var hlg = GetComponentInChildren<HorizontalLayoutGroup>();
            if (hlg != null)
                panelTransform = hlg.transform;
        }
        if (panelTransform == null)
        {
            Debug.LogError("[ChartPanel] Missing Panel");
            return;
        }

        var containerTransform = panelTransform.Find("ChartContainer");
        if (containerTransform == null)
        {
            var go = new GameObject("ChartContainer");
            go.AddComponent<RectTransform>();
            containerTransform = go.transform;
            containerTransform.SetParent(panelTransform, false);
            var le = go.AddComponent<LayoutElement>();
            le.preferredWidth = 1200;
            le.preferredHeight = 600;
            le.flexibleWidth = 1;
            le.flexibleHeight = 1;
        }
        chartContainer = containerTransform.gameObject;

        WireButton(panelTransform, "PrevButton", PrevChart, "◀");
        WireButton(panelTransform, "NextButton", NextChart, "▶");

        panelTransform.Find("PrevButton").SetSiblingIndex(0);
        panelTransform.Find("ChartContainer").SetSiblingIndex(1);
        panelTransform.Find("NextButton").SetSiblingIndex(2);

        InitBuffers();
        CreateCharts();
        initialized = true;
        ShowChart(0);
    }

    private void WireButton(Transform panel, string name, UnityEngine.Events.UnityAction action, string label)
    {
        var btn = panel.Find(name)?.GetComponent<Button>();
        if (btn == null)
        {
            var go = new GameObject(name);
            go.transform.SetParent(panel, false);
            btn = go.AddComponent<Button>();
            var img = go.AddComponent<Image>();
            img.color = new Color(0.15f, 0.15f, 0.2f);
            var le = go.AddComponent<LayoutElement>();
            le.preferredWidth = 50;
            le.preferredHeight = 600;
            le.flexibleWidth = 0;
            le.flexibleHeight = 0;

            var txtGo = new GameObject("Text");
            txtGo.transform.SetParent(go.transform, false);
            var txtRt = txtGo.AddComponent<RectTransform>();
            txtRt.anchorMin = Vector2.zero;
            txtRt.anchorMax = Vector2.one;
            txtRt.sizeDelta = Vector2.zero;
            var txt = txtGo.AddComponent<Text>();
            txt.text = label;
            txt.fontSize = 28;
            txt.alignment = TextAnchor.MiddleCenter;
            txt.color = Color.white;
            txt.font = defaultFont;
        }
        btn.onClick.RemoveListener(action);
        btn.onClick.AddListener(action);
    }

    private void InitBuffers()
    {
        strainBuffer = new float[chartCapacity];
        damageBuffer = new float[chartCapacity];
        stressBuffer = new float[chartCapacity];
    }

    private T CreateChart<T>(string name, string title) where T : BaseChart
    {
        var go = new GameObject(name);
        var rt = go.AddComponent<RectTransform>();
        rt.SetParent(chartContainer.transform, false);
        rt.anchorMin = Vector2.zero;
        rt.anchorMax = Vector2.one;
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;

        var chart = go.AddComponent<T>();
        chart.Init();
        chart.RemoveData();

        var chartTitle = chart.EnsureChartComponent<Title>();
        chartTitle.show = true;
        chartTitle.text = title;

        var xAxis = chart.EnsureChartComponent<XAxis>();
        xAxis.type = Axis.AxisType.Category;
        xAxis.boundaryGap = false;

        var yAxis = chart.EnsureChartComponent<YAxis>();
        yAxis.type = Axis.AxisType.Value;
        yAxis.axisLabel.numericFormatter = "F2";

        return chart;
    }

    private void InitChartData(BaseChart chart)
    {
        chart.ClearData();
        for (int i = 0; i < chartCapacity; i++)
        {
            chart.AddXAxisData(i.ToString());
            chart.AddData(0, 0f);
        }
    }

    private void CreateCharts()
    {
        strainChart = CreateChart<LineChart>("StrainChart", "Strain Timeseries");
        strainChart.AddSerie<Line>("Strain");
        InitChartData(strainChart);
        var strainY = strainChart.EnsureChartComponent<YAxis>();
        strainY.axisName.show = true;
        strainY.axisName.name = "Strain";

        damageChart = CreateChart<LineChart>("DamageChart", "Damage Progress");
        damageChart.AddSerie<Line>("Damage");
        InitChartData(damageChart);
        var damageY = damageChart.EnsureChartComponent<YAxis>();
        damageY.axisName.show = true;
        damageY.axisName.name = "Damage";

        stressChart = CreateChart<LineChart>("StressChart", "Stress Over Time");
        stressChart.AddSerie<Line>("Stress");
        stressChart.AddSerie<Line>("Yield");
        InitChartData(stressChart);
        for (int i = 0; i < chartCapacity; i++)
            stressChart.AddData(1, currentYield);
        var stressY = stressChart.EnsureChartComponent<YAxis>();
        stressY.axisName.show = true;
        stressY.axisName.name = "Stress (Pa)";
        var stressGrid = stressChart.EnsureChartComponent<GridCoord>();
        stressGrid.left = 0.25f;

        rainflowChart = CreateChart<BarChart>("RainflowChart", "Rainflow Cycle Histogram");
        rainflowChart.AddSerie<Bar>("Cycles");
        var rainflowSerie = rainflowChart.GetSerie(0);
        if (rainflowSerie != null) rainflowSerie.animation.enable = false;
        var rfXAxis = rainflowChart.EnsureChartComponent<XAxis>();
        rfXAxis.type = Axis.AxisType.Category;
        rfXAxis.boundaryGap = true;
        rfXAxis.axisName.show = true;
        rfXAxis.axisName.name = "MPa";
        var rfYAxis = rainflowChart.EnsureChartComponent<YAxis>();
        rfYAxis.min = 0f;
        rfYAxis.axisName.show = true;
        rfYAxis.axisName.name = "Cycle Count";
        var rfGrid = rainflowChart.EnsureChartComponent<GridCoord>();
        rfGrid.left = 0.15f;

        charts = new List<BaseChart> { strainChart, damageChart, stressChart, rainflowChart };
    }

    public void PushStrain(float value)
    {
        if (!initialized) return;
        strainBuffer[strainHead] = value;
        strainHead = (strainHead + 1) % chartCapacity;
        if (strainCount < chartCapacity) strainCount++;

        if (Mathf.Abs(value) > maxStrain) maxStrain = Mathf.Abs(value);
        var yAxis = strainChart.EnsureChartComponent<YAxis>();
        yAxis.min = -maxStrain * 1.1f;
        yAxis.max = maxStrain * 1.1f;

        int idx = (strainHead - 1 + chartCapacity) % chartCapacity;
        strainChart.UpdateData(0, idx, value);
    }

    public void PushDamage(float value)
    {
        if (!initialized) return;
        damageBuffer[damageHead] = value;
        damageHead = (damageHead + 1) % chartCapacity;
        if (damageCount < chartCapacity) damageCount++;
        if (Mathf.Abs(value) > maxDamage) maxDamage = Mathf.Abs(value);
        var yAxis = damageChart.EnsureChartComponent<YAxis>();
        yAxis.min = 0f;
        yAxis.max = Mathf.Max(maxDamage * 1.1f, 0.1f);
        int idx = (damageHead - 1 + chartCapacity) % chartCapacity;
        damageChart.UpdateData(0, idx, value);
        damageChart.RefreshChart();
    }

    public void PushStress(float value, float yieldPoint)
    {
        if (!initialized) return;
        float newYield = yieldPoint > 0 ? yieldPoint : currentYield;
        bool yieldChanged = !Mathf.Approximately(newYield, currentYield);
        currentYield = newYield;

        stressBuffer[stressHead] = value;
        stressHead = (stressHead + 1) % chartCapacity;
        if (stressCount < chartCapacity) stressCount++;
        if (Mathf.Abs(value) > maxStress) maxStress = Mathf.Abs(value);

        float axisMax = Mathf.Max(maxStress, currentYield) * 1.1f;
        var stressYAxis = stressChart.EnsureChartComponent<YAxis>();
        stressYAxis.min = 0f;
        stressYAxis.max = axisMax;

        int idx = (stressHead - 1 + chartCapacity) % chartCapacity;
        stressChart.UpdateData(0, idx, value);

        if (yieldChanged)
        {
            for (int i = 0; i < chartCapacity; i++)
                stressChart.UpdateData(1, i, currentYield);
        }
        else
        {
            stressChart.UpdateData(1, idx, currentYield);
        }

        stressChart.RefreshChart();
    }

    public void SetRainflowBins(float[] ranges, float[] counts)
    {
        if (!initialized) return;
        if (ranges == null || counts == null || ranges.Length == 0 || ranges.Length != counts.Length)
            return;

        var xAxis = rainflowChart.EnsureChartComponent<XAxis>();
        var yAxis = rainflowChart.EnsureChartComponent<YAxis>();
        yAxis.min = 0f;

        if (lastRainflowBinCount != counts.Length)
        {
            xAxis.ClearData();
            rainflowChart.ClearData();
            for (int i = 0; i < ranges.Length; i++)
            {
                rainflowChart.AddXAxisData(ranges[i].ToString("F1"));
                rainflowChart.AddData(0, counts[i]);
            }
        }
        else
        {
            for (int i = 0; i < ranges.Length; i++)
            {
                rainflowChart.UpdateData(0, i, counts[i]);
                rainflowChart.UpdateXAxisData(0, ranges[i].ToString("F1"), i);
            }
        }

        lastRainflowBinCount = counts.Length;
        float maxCount = 1f;
        for (int i = 0; i < counts.Length; i++)
            if (counts[i] > maxCount) maxCount = counts[i];

        yAxis.max = maxCount * 1.15f;
        rainflowChart.RefreshChart();
    }

    public void NextChart()
    {
        if (!initialized) return;
        ShowChart((currentIndex + 1) % charts.Count);
    }
    public void PrevChart()
    {
        if (!initialized) return;
        ShowChart((currentIndex - 1 + charts.Count) % charts.Count);
    }

    private void ShowChart(int index)
    {
        for (int i = 0; i < charts.Count; i++)
            charts[i].gameObject.SetActive(i == index);

        currentIndex = index;
        charts[index].RefreshChart();
    }
}