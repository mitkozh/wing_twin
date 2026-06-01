using NativeWebSocket;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Linq;
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
            if (ws != null)
            {
                try { _ = ws.Close(); } catch { }
            }

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

    private async void ScheduleReconnect()
    {
        if (reconnectScheduled) return;
        reconnectScheduled = true;

        Debug.Log($"[WS] Scheduling reconnect in {currentReconnectDelay}s...");
        await Task.Delay(TimeSpan.FromSeconds(currentReconnectDelay));
        reconnectScheduled = false;

        await ConnectAsync();
        currentReconnectDelay = Mathf.Min(currentReconnectDelay * 1.5f, maxReconnectDelay);
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
        chartPanel.PushStress(data.stress_max, data.yield_point_pa > 0 ? data.yield_point_pa : yieldPointPa);

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
                var cmdResponse = JsonConvert.DeserializeObject<CommandResponse>(json);
                if (cmdResponse.cmd == "status")
                {
                    var status = JsonConvert.DeserializeObject<StatusResponse>(json);
                    currentDamage = status.damage;
                    currentSpeed = status.speed;
                    currentState = status.led_state;
                    currentConfidence = status.confidence;
                    Enqueue(UpdateUI);
                }
                else if (cmdResponse.cmd == "pong")
                {
                    Debug.Log("[WS] Heartbeat received");
                }
                return;
            }

            var data = JsonConvert.DeserializeObject<TwinState>(json);
            if (data == null) return;

            currentDamage = data.damage;
            currentAvgDamage = data.avg_damage;
            currentSpeed = data.speed;
            currentState = data.led_state;
            currentConfidence = data.confidence;
            stressMin = data.stress_min;
            stressMax = data.stress_max;
            yieldPointPa = data.yield_point_pa > 0 ? data.yield_point_pa : yieldPointPa;
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

            string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
            string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

            if (stepsSliderLabel != null)
                stepsSliderLabel.text = $"Steps: {data.stepper_position}";
            if (angleSliderLabel != null)
                angleSliderLabel.text = $"<color={desiredHex}>Desired Angle: {planeAngleSlider.value:F1}</color> | <color={allowedHex}>Allowed Angle: {targetAngleOfAttack:F1}{'\u00b0'}</color>";
            if (speedSliderLabel != null)
                speedSliderLabel.text = $"<color={desiredHex}>Desired Speed: {speedSlider.value:F1}</color> | <color={allowedHex}>Allowed Speed: {targetPlaneSpeed:F1} km/h</color>";

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
            string requestId = cmd + "_" + System.DateTime.Now.Ticks;
            pendingCommands[requestId] = callback;
        }
    }
}
