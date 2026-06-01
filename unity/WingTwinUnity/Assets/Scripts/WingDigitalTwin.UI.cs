using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;

public partial class WingDigitalTwin : MonoBehaviour
{
    private bool QueryUIElements()
    {
        if (uiDocument == null)
            uiDocument = GetComponent<UIDocument>();
        if (uiDocument == null || uiDocument.rootVisualElement == null)
        {
            Debug.LogError("UIDocument not found or not initialized. Add UIDocument component to this GameObject.");
            return false;
        }

        var root = uiDocument.rootVisualElement;

        damageSliderFill = root.Q("damage-slider-fill");
        damageLabel = root.Q<Label>("damage-label");
        avgDamageSliderFill = root.Q("avg-damage-slider-fill");
        avgDamageLabel = root.Q<Label>("avg-damage-label");
        speedLabel = root.Q<Label>("speed-label");
        confidenceLabel = root.Q<Label>("confidence-label");
        connectionLabel = root.Q<Label>("connection-label");
        heatmapToggle = root.Q<Toggle>("heatmap-toggle");
        if (heatmapToggle != null)
        {
            var checkmark = heatmapToggle.Q(null, "unity-toggle__checkmark");
            if (checkmark != null)
            {
                checkmark.style.borderTopWidth = 1;
                checkmark.style.borderBottomWidth = 1;
                checkmark.style.borderLeftWidth = 1;
                checkmark.style.borderRightWidth = 1;
                var bColor = new Color(0, 0, 0, 0.35f);
                checkmark.style.borderTopColor = bColor;
                checkmark.style.borderRightColor = bColor;
                checkmark.style.borderBottomColor = bColor;
                checkmark.style.borderLeftColor = bColor;
                checkmark.style.borderTopLeftRadius = 3;
                checkmark.style.borderTopRightRadius = 3;
                checkmark.style.borderBottomLeftRadius = 3;
                checkmark.style.borderBottomRightRadius = 3;
            }
        }
        stressBar = root.Q("stress-bar");

        planeAngleSlider = root.Q<Slider>("angle-slider");
        stepsSlider = root.Q<Slider>("steps-slider");
        speedSlider = root.Q<Slider>("speed-slider");
        allowedAngleFill = root.Q("allowed-angle-fill");
        allowedSpeedFill = root.Q("allowed-speed-fill");
        angleSliderLabel = root.Q<Label>("angle-slider-label");
        stepsSliderLabel = root.Q<Label>("steps-slider-label");
        speedSliderLabel = root.Q<Label>("speed-slider-label");

        helpPanel = root.Q("help-panel");

        Button helpBtn = root.Q<Button>("help-button");
        if (helpBtn != null)
            helpBtn.clicked += () => ToggleHelp();
        Button helpCloseBtn = root.Q<Button>("help-close-btn");
        if (helpCloseBtn != null)
            helpCloseBtn.clicked += () => ToggleHelp();

        Button viewBtn1 = root.Q<Button>("view-btn-1");
        Button viewBtn2 = root.Q<Button>("view-btn-2");
        Button viewBtn3 = root.Q<Button>("view-btn-3");
        if (viewBtn1 != null) viewBtn1.clicked += () => SwitchViewButton(1);
        if (viewBtn2 != null) viewBtn2.clicked += () => SwitchViewButton(2);
        if (viewBtn3 != null) viewBtn3.clicked += () => SwitchViewButton(3);

        viewGroups = new VisualElement[3];
        viewGroups[0] = root.Q("view-group-1");
        viewGroups[1] = root.Q("view-group-2");
        viewGroups[2] = root.Q("view-group-3");

        leftPanel = root.Q("left-panel");
        flightMetricsPanel = root.Q("flight-metrics-panel");
        stressLegend = root.Q("stress-legend");
        notificationContainer = root.Q("notification-container");

        stressLabels = new Label[6];
        for (int i = 0; i < 6; i++)
            stressLabels[i] = root.Q<Label>($"stress-label-{i}");

        planeSpeedLabel = root.Q<Label>("plane-speed-label");
        planeAngleLabel = root.Q<Label>("plane-angle-label");

        metricAltitude = root.Q<Label>("metric-altitude");
        metricDistance = root.Q<Label>("metric-distance");
        metricTotal = root.Q<Label>("metric-total");
        metricFlights = root.Q<Label>("metric-flights");
        metricRemaining = root.Q<Label>("metric-remaining");

        takeoffBtn = root.Q<Button>("takeoff-btn");
        landBtn = root.Q<Button>("land-btn");
        preflightControls = root.Q("preflight-controls");
        inflightControls = root.Q("inflight-controls");
        preflightTitle = root.Q<Label>("preflight-title");
        preflightSlider = root.Q<Slider>("preflight-slider");
        preflightSliderValue = root.Q<Label>("preflight-slider-value");
        preflightSubmitBtn = root.Q<Button>("preflight-submit-btn");

        if (preflightSlider != null)
        {
            preflightSlider.RegisterValueChangedCallback(evt =>
            {
                if (preflightSliderValue != null)
                    preflightSliderValue.text = $"{evt.newValue:F0} km";
            });
            preflightSlider.SetValueWithoutNotify(10f);
            if (preflightSliderValue != null)
                preflightSliderValue.text = "10 km";
        }

        if (takeoffBtn != null)
            takeoffBtn.clicked += OnTakeoffClicked;
        if (landBtn != null)
            landBtn.clicked += OnLandClicked;
        if (preflightSubmitBtn != null)
            preflightSubmitBtn.clicked += OnPreflightSubmit;

        Color allowedFillColor = new Color(0f, 0.86f, 0.31f, 0.55f);
        if (allowedAngleFill != null)
            allowedAngleFill.style.backgroundColor = allowedFillColor;
        if (allowedSpeedFill != null)
            allowedSpeedFill.style.backgroundColor = allowedFillColor;

        UpdateLegendValues();
        return true;
    }

    private void UpdatePlaneSpeed()
    {
        if (planeSpeedLabel != null)
            planeSpeedLabel.text = $"Current Plane Speed: {currentPlaneSpeed:F1}";

        foreach (ParticleSystem ps in windParticles)
        {
            float change = currentPlaneSpeed / commonPlaneSpeed;
            ParticleSystem.MainModule main = ps.main;
            float speed = change * windExaggeration;
            main.startSpeed = speed;
            main.startLifetime = 10f / speed;
        }
    }

    private void UpdatePlaneAngle()
    {
        if (rotationalPivot != null)
            rotationalPivot.transform.localRotation = Quaternion.Euler(currentPlaneAngle, 0, 0);

        if (planeAngleLabel != null)
            planeAngleLabel.text = $"Current Plane Angle: {currentPlaneAngle:F1}";
    }

    private void UpdatePlaneLabelPositions()
    {
        Camera cam = GetActiveCamera();
        if (cam == null || rotationalPivot == null)
            return;

        Vector3 screenPos = cam.WorldToScreenPoint(rotationalPivot.transform.position);

        if (screenPos.z < 0f)
        {
            if (planeSpeedLabel != null) planeSpeedLabel.style.display = DisplayStyle.None;
            if (planeAngleLabel != null) planeAngleLabel.style.display = DisplayStyle.None;
            return;
        }

        float x = screenPos.x;
        float y = Screen.height - screenPos.y;

        if (planeSpeedLabel != null)
        {
            planeSpeedLabel.style.display = DisplayStyle.Flex;
            planeSpeedLabel.style.left = x - 80;
            planeSpeedLabel.style.top = y - 50;
        }
        if (planeAngleLabel != null)
        {
            planeAngleLabel.style.display = DisplayStyle.Flex;
            planeAngleLabel.style.left = x - 80;
            planeAngleLabel.style.top = y - 28;
        }
    }

    public void SwitchViewButton(int camera)
    {
        SwitchView(camera);
    }

    private void SwitchView(int camera)
    {
        int index = camera - 1;
        bool planeSceneNeeded = false;

        for (int i = 0; i < UIViewGroups.Count; i++)
        {
            GameObject viewCamera = UIViewGroups[i].viewCamera;
            GameObject worldUIGroup = UIViewGroups[i].worldUIViewGroup;

            bool active = i == index;

            if (worldUIGroup != null)
                worldUIGroup.SetActive(active);
            if (viewCamera != null)
                viewCamera.SetActive(active);
            if (active && UIViewGroups[i].needPlaneScene)
                planeSceneNeeded = true;
        }

        for (int i = 0; i < viewGroups.Length; i++)
        {
            if (viewGroups[i] != null)
                viewGroups[i].style.display = i == index ? DisplayStyle.Flex : DisplayStyle.None;
        }

        bool isView1 = index == 0;
        if (leftPanel != null)
            leftPanel.style.display = isView1 ? DisplayStyle.Flex : DisplayStyle.None;
        if (flightMetricsPanel != null)
            flightMetricsPanel.style.display = isView1 ? DisplayStyle.Flex : DisplayStyle.None;
        if (stressLegend != null)
            stressLegend.style.display = isView1 ? DisplayStyle.Flex : DisplayStyle.None;
        if (notificationContainer != null)
            notificationContainer.style.display = isView1 ? DisplayStyle.Flex : DisplayStyle.None;

        planeScene.SetActive(planeSceneNeeded);

        if (view3Axes != null)
            view3Axes.SetActive(index == 2);
    }

    void UpdateUI()
    {
        UpdateDamageSlider(damageSliderFill, damageLabel, currentDamage, "Max Damage");
        UpdateDamageSlider(avgDamageSliderFill, avgDamageLabel, currentAvgDamage, "Avg Damage");

        if (confidenceLabel != null) confidenceLabel.text = $"Confidence: {currentConfidence:F1}%";

        UpdateFlightMetrics();
        UpdateControlPanelMode();
    }

    void UpdateDamageSlider(VisualElement fill, Label label, float value, string title)
    {
        if (fill != null)
        {
            fill.style.width = Length.Percent(value * 100f);
            Color sliderColor = value switch
            {
                >= 0.8f => redColor,
                >= 0.3f => yellowColor,
                _ => greenColor,
            };
            fill.style.backgroundColor = sliderColor;
        }
        if (label != null)
            label.text = $"{title}: {value * 100:F1}%";
    }

    public void ToggleHelp()
    {
        if (helpPanel != null)
            helpPanel.style.display = helpPanel.style.display == DisplayStyle.None ? DisplayStyle.Flex : DisplayStyle.None;
    }

    public void ToggleHeatmapMode()
    {
        showDamageHeatmap = !showDamageHeatmap;
        if (heatmapToggle != null)
            heatmapToggle.SetValueWithoutNotify(showDamageHeatmap);
        UpdateHeatmapToggleLabel(showDamageHeatmap);
        SendCommand("set_heatmap_mode", new Dictionary<string, object> { { "mode", showDamageHeatmap ? "damage" : "stress" } });
        Debug.Log($"[HEATMAP] Mode: {(showDamageHeatmap ? "DAMAGE" : "STRESS")}");
    }

    void OnHeatmapModeChanged(bool isOn)
    {
        showDamageHeatmap = isOn;
        UpdateHeatmapToggleLabel(isOn);
        SendCommand("set_heatmap_mode", new Dictionary<string, object> { { "mode", isOn ? "damage" : "stress" } });
        Debug.Log($"[HEATMAP] Mode: {(showDamageHeatmap ? "DAMAGE" : "STRESS")}");
    }

    void UpdateHeatmapToggleLabel(bool isDamageMode)
    {
        if (heatmapToggle != null)
            heatmapToggle.label = isDamageMode ? "Damage" : "Stress";
    }

    void UpdateFlightMetrics()
    {
        if (metricAltitude != null) metricAltitude.text = $"Alt: {altitude:F1} m";
        if (metricDistance != null) metricDistance.text = $"Dist: {kmThisFlight:F3} km";
        if (metricTotal != null) metricTotal.text = $"Total: {totalKmFlown + kmThisFlight:F1} km";
        if (metricFlights != null) metricFlights.text = $"Flights: {flightNumber + 1}";
        if (metricRemaining != null)
            metricRemaining.text = remainingKm > 0 && !float.IsInfinity(remainingKm)
                ? $"Remaining: {remainingKm:F1} km"
                : "Remaining: -- km";
    }

    void UpdateControlPanelMode()
    {
        bool showPreflight = flightPhase == "on_ground";
        bool showInflight = flightPhase != "on_ground";
        bool showTakeoff = flightPhase == "on_ground";
        bool showLand = flightPhase == "in_flight";
        bool locked = flightPhase == "taking_off" || flightPhase == "landing";

        if (preflightControls != null)
            preflightControls.style.display = showPreflight ? DisplayStyle.Flex : DisplayStyle.None;
        if (inflightControls != null)
            inflightControls.style.display = showInflight ? DisplayStyle.Flex : DisplayStyle.None;
        if (takeoffBtn != null)
        {
            takeoffBtn.style.display = showTakeoff ? DisplayStyle.Flex : DisplayStyle.None;
            if (showTakeoff)
                takeoffBtn.SetEnabled(preFlightSafe && flightAllowed && !locked);
        }
        if (landBtn != null)
        {
            landBtn.style.display = showLand ? DisplayStyle.Flex : DisplayStyle.None;
            if (showLand)
                landBtn.SetEnabled(altitude <= maxLandingAltitude && !locked);
        }

        LockControls(locked);
    }

    void LockControls(bool locked)
    {
        controlsLocked = locked;
        if (planeAngleSlider != null) planeAngleSlider.SetEnabled(!locked);
        if (speedSlider != null) speedSlider.SetEnabled(!locked);
        if (stepsSlider != null) stepsSlider.SetEnabled(!locked);
        if (preflightSlider != null) preflightSlider.SetEnabled(!locked);
        if (preflightSubmitBtn != null) preflightSubmitBtn.SetEnabled(!locked);
    }

    void OnPreflightSubmit()
    {
        if (controlsLocked || preflightSlider == null) return;
        float dist = preflightSlider.value;
        if (dist <= 0) return;
        if (toastManager != null)
            toastManager.Show("pf_checking", "info", "Pre-Flight", $"Checking {dist:F0} km...", null);
        SendCommand("plan_flight", new Dictionary<string, object> { { "planned_km", dist } });
    }

    void OnTakeoffClicked()
    {
        if (controlsLocked) return;
        if (takeoffBtn != null) takeoffBtn.SetEnabled(false);
        if (toastManager != null)
            toastManager.Show("to_taking_off", "info", "Takeoff", "Initiating takeoff...", null);
        SendCommand("takeoff");
    }

    void OnLandClicked()
    {
        if (controlsLocked) return;
        if (landBtn != null) landBtn.SetEnabled(false);
        if (toastManager != null)
            toastManager.Show("ld_landing", "info", "Landing", "Initiating landing...", null);
        SendCommand("land");
    }

    public void UI_Pause()  => SendCommand("pause");
    public void UI_Reset()  => SendCommand("reset",
        new Dictionary<string, object> { { "target", "damage" } });
    public void UI_Status() => SendCommand("status");

    void OnAngleSliderChanged(float angle)
    {
        string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
        string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

        UpdateSliderLabel(angleSliderLabel, $"<color={desiredHex}>Desired Angle: {planeAngleSlider.value:F1}</color> | <color={allowedHex}>Allowed Angle: {targetAngleOfAttack:F1}{'\u00b0'}</color>");

        float speed = speedSlider != null ? speedSlider.value : currentPlaneSpeed;
        SendFlightState(angle, speed);
    }

    void OnSpeedSliderChanged(float speed)
    {
        string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
        string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

        UpdateSliderLabel(speedSliderLabel, $"<color={desiredHex}>Desired Speed: {speedSlider.value:F1}</color> | <color={allowedHex}>Allowed Speed: {targetPlaneSpeed:F1} km/h</color>");

        float angle = planeAngleSlider != null ? planeAngleSlider.value : 0f;
        SendFlightState(angle, speed);
    }

    void UpdateSliderLabel(Label label, string text)
    {
        if (label != null) label.text = text;
    }
}
