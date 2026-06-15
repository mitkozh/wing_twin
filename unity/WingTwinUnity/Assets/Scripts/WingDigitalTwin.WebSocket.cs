using NativeWebSocket;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UIElements;

public partial class WingDigitalTwin : MonoBehaviour
{
    async Task ConnectAsync()
    {
        if (connected) return;

        try
        {
            ws = new WebSocket(serverUrl);
            ws.OnOpen += () =>
            {
                connected = true;
                reconnectScheduled = false;
                currentReconnectDelay = reconnectDelay;
                lastHeartbeatTime = Time.time;
                lastMessageTime = Time.time;
                Debug.Log("[WS] Connected");
            };
            ws.OnMessage += (byte[] data) =>
            {
                lastMessageTime = Time.time;
                string msg = System.Text.Encoding.UTF8.GetString(data);
                Enqueue(() => HandleMessage(msg));
            };
            ws.OnClose += (code) =>
            {
                connected = false;
                Debug.Log($"[WS] Closed: {code}");
                if (!reconnectScheduled)
                    ScheduleReconnect();
            };
            ws.OnError += (err) =>
            {
                Debug.LogError($"[WS] Error: {err}");
                connected = false;
                if (!reconnectScheduled)
                    ScheduleReconnect();
            };

            await ws.Connect();
        }
        catch (Exception e)
        {
            Debug.LogError($"[WS] Connection error: {e.Message}");
            if (!reconnectScheduled)
                ScheduleReconnect();
        }
    }

    private CancellationTokenSource _reconnectCts;

    private async void ScheduleReconnect()
    {
        if (reconnectScheduled) return;
        reconnectScheduled = true;

        _reconnectCts?.Cancel();
        _reconnectCts = new CancellationTokenSource();
        var token = _reconnectCts.Token;

        try
        {
            Debug.Log($"[WS] Scheduling reconnect in {currentReconnectDelay}s...");
            await Task.Delay(TimeSpan.FromSeconds(currentReconnectDelay), token);
            token.ThrowIfCancellationRequested();

            await ConnectAsync();
            currentReconnectDelay = Mathf.Min(currentReconnectDelay * 1.5f, maxReconnectDelay);
        }
        catch (OperationCanceledException)
        {
            Debug.Log("[WS] Reconnect cancelled");
        }
        finally
        {
            reconnectScheduled = false;
        }
    }

    private void SendHeartbeat()
    {
        if (ws != null && ws.State == WebSocketState.Open)
            ws.SendText("{\"cmd\":\"ping\"}");
    }

    void PushChartData(TwinState data)
    {
        if (chartPanel == null) return;

        chartPanel.PushStrain(data.strain);
        chartPanel.PushDamage(data.damage);
        chartPanel.PushStress(data.stress_max,
            data.yield_point_pa > 0 ? data.yield_point_pa : yieldPointPa,
            data.stress_limit_pa > 0 ? data.stress_limit_pa : stressLimitPa);

        if (data.cycles_binned != null && data.cycles_binned.Count > 0)
        {
            float[] ranges = data.cycles_binned.Select(c => c.range).ToArray();
            float[] counts = data.cycles_binned.Select(c => c.count).ToArray();
            chartPanel.SetRainflowBins(ranges, counts);
        }
    }

    void HandleMessage(string json)
    {
        try
        {
            if (json.Contains("\"cmd\":"))
            {
                CheckPendingCallbacks(json);

                var cmdDict = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                string cmdType = cmdDict?.ContainsKey("cmd") == true ? cmdDict["cmd"]?.ToString() : "";
                switch (cmdType)
                {
                    case "pong":
                        Debug.Log("[WS] Heartbeat received");
                        break;
                    case "plan_flight_result":
                    {
                        Enqueue(() =>
                        {
                            try
                            {
                                var result = JsonConvert.DeserializeObject<PlanFlightResult>(json);
                                if (result != null)
                                {
                                    preFlightSafe = result.safe;
                                    if (result.safe)
                                    {
                                        if (toastManager != null)
                                            toastManager.Show("pf_safe", "info", "Pre-Flight",
                                                $"Safe - remaining: {result.remaining_km:F1} km", null);
                                    }
                                    else
                                    {
                                        if (toastManager != null)
                                            toastManager.Show("pf_warning", "warning", "Pre-Flight",
                                                result.warning, null);
                                    }
                                    if (takeoffBtn != null && flightPhase == "on_ground")
                                        takeoffBtn.SetEnabled(preFlightSafe && flightAllowed);
                                }
                            }
                            catch { }
                        });
                        break;
                    }
                    case "ack":
                        break;
                    case "error":
                    {
                        var jObj = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                        string msg = jObj?.ContainsKey("message") == true ? jObj["message"]?.ToString() : "Unknown error";
                        Enqueue(() =>
                        {
                            if (toastManager != null)
                                toastManager.Show("err_" + Guid.NewGuid().ToString("N"), "error", "Error", msg, null);
                            if (takeoffBtn != null && flightPhase == "on_ground")
                                takeoffBtn.SetEnabled(preFlightSafe && flightAllowed);
                            if (landBtn != null && flightPhase == "in_flight")
                                landBtn.SetEnabled(altitude <= maxLandingAltitude);
                        });
                        break;
                    }
                }
                return;
            }

            var data = JsonConvert.DeserializeObject<TwinState>(json);
            if (data == null) return;

            currentDamage = data.damage;
            currentAvgDamage = data.avg_damage;
            currentConfidence = data.confidence;
            stressMin = data.stress_min;
            stressMax = data.stress_max;
            yieldPointPa = data.yield_point_pa > 0 ? data.yield_point_pa : yieldPointPa;
            stressLimitPa = data.stress_limit_pa > 0 ? data.stress_limit_pa : stressLimitPa;
            if (data.max_angle_deg > 0) {
                maxAngleDeg = data.max_angle_deg;
                planeAngleSlider.lowValue = -maxAngleDeg;
                planeAngleSlider.highValue = maxAngleDeg;

            }
            if (data.max_speed_kmh > 0) {
                maxSpeedKmh = data.max_speed_kmh;
                speedSlider.highValue = maxSpeedKmh;
            }
            if (data.max_stepper_steps > 0) {
                maxStepperSteps = data.max_stepper_steps;
                stepsSlider.highValue = maxStepperSteps;
            }

            currentPlaneAngle = data.new_angle_of_attack;
            currentPlaneSpeed = data.new_speed;
            targetAngleOfAttack = data.target_angle_of_attack;
            targetPlaneSpeed = data.target_speed;
            desiredAngleOfAttack = data.desired_angle_of_attack;
            desiredPlaneSpeed = data.desired_speed;

            string newPhase = data.flight_phase ?? "on_ground";
            flightPhase = newPhase;

            if (flightPhase == "taking_off" || flightPhase == "landing")
            {
                planeAngleSlider.SetValueWithoutNotify(desiredAngleOfAttack);
                speedSlider.SetValueWithoutNotify(desiredPlaneSpeed);
            }

            altitude = data.altitude;
            kmThisFlight = data.km_this_flight;
            totalKmFlown = data.total_km_flown;
            flightNumber = data.flight_number;
            remainingKm = data.remaining_km;
            flightAllowed = data.flight_allowed;
            maxLandingAltitude = data.max_landing_altitude;
            plannedKm = data.planned_km;
            preFlightSafe = data.pre_flight_safe;
            maintenanceAssist = data.maintenance_assist;
            if (maintenanceToggle != null)
                maintenanceToggle.SetValueWithoutNotify(maintenanceAssist);

            if (!string.IsNullOrEmpty(data.heatmap_mode))
            {
                bool isDamageMode = data.heatmap_mode == "damage";
                if (isDamageMode != showDamageHeatmap)
                {
                    showDamageHeatmap = isDamageMode;
                    if (heatmapToggle != null)
                        heatmapToggle.SetValueWithoutNotify(showDamageHeatmap);
                    UpdateHeatmapToggleLabel(showDamageHeatmap);
                }
            }

            string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
            string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

            if (stepsSliderLabel != null)
                stepsSliderLabel.text = $"Steps: {data.stepper_position}";
            if (angleSliderLabel != null)
                angleSliderLabel.text = $"<color={desiredHex}>Desired Angle: {desiredAngleOfAttack:F1}</color> | <color={allowedHex}>Allowed Angle: {targetAngleOfAttack:F1}{'\u00b0'}</color>";
            if (speedSliderLabel != null)
                speedSliderLabel.text = $"<color={desiredHex}>Desired Speed: {desiredPlaneSpeed:F1}</color> | <color={allowedHex}>Allowed Speed: {targetPlaneSpeed:F1} km/h</color>";

            if (stepsSlider != null)
                stepsSlider.SetValueWithoutNotify(data.stepper_position);
            if (allowedAngleFill != null && maxAngleDeg > 0f)
            {
                float pct = (targetAngleOfAttack + maxAngleDeg) / (2f * maxAngleDeg) * 100f;
                allowedAngleFill.style.width = Length.Percent(Mathf.Clamp(pct, 0f, 100f));
            }
            if (allowedSpeedFill != null && maxSpeedKmh > 0f)
            {
                float pct = targetPlaneSpeed / maxSpeedKmh * 100f;
                allowedSpeedFill.style.width = Length.Percent(Mathf.Clamp(pct, 0f, 100f));
            }

            if (data.stress_field != null && data.stress_field.Count > 0)
                stressField = data.stress_field.ToArray();
            if (data.deformation_field != null && data.deformation_field.Count > 0)
                deformationField = data.deformation_field.ToArray();
            if (data.node_damages != null && data.node_damages.Count > 0)
                nodeDamages = data.node_damages.ToArray();

            Enqueue(UpdateUI);
            Enqueue(() => ProcessNotifications(data.notifications));
            Enqueue(() => UpdateWingVisualization(data));
            Enqueue(() => PushChartData(data));
        }
        catch (Exception ex)
        {
            Debug.LogError($"[WS] Parse error: {ex.Message}");
        }
    }

    void SendCommand(string cmd, Dictionary<string, object> args = null, Action<string> callback = null)
    {
        if (ws == null || ws.State != WebSocketState.Open) return;

        var payload = new Dictionary<string, object> { { "cmd", cmd } };
        if (args != null)
        {
            foreach (var kv in args) payload[kv.Key] = kv.Value;
        }

        string json = JsonConvert.SerializeObject(payload);
        ws.SendText(json);

        if (callback != null)
        {
            string requestId = cmd + "_" + DateTime.Now.Ticks;
            pendingCommands[requestId] = callback;
        }
    }

    void CheckPendingCallbacks(string json)
    {
        if (pendingCommands.Count == 0) return;
        try
        {
            var dict = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
            if (dict == null) return;
            string responseCmd = dict.ContainsKey("cmd") ? dict["cmd"]?.ToString() : "";
            var matching = pendingCommands.Where(kv => kv.Key.StartsWith(responseCmd)).ToList();
            foreach (var kv in matching)
            {
                try { kv.Value.Invoke(json); } catch { }
                pendingCommands.Remove(kv.Key);
            }
        }
        catch { }
    }

    [Serializable]
    public class PlanFlightResult
    {
        public string cmd;
        public bool safe;
        public float remaining_km;
        public float planned_km;
        public string warning;
    }
}
