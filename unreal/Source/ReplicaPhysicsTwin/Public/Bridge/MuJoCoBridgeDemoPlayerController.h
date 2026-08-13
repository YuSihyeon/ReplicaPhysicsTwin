#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "MuJoCoBridgeDemoPlayerController.generated.h"

/** Receives Phase 3 keyboard commands from the active Unreal viewport. */
UCLASS()
class REPLICAPHYSICSTWIN_API AMuJoCoBridgeDemoPlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	AMuJoCoBridgeDemoPlayerController();

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void SetupInputComponent() override;

private:
	bool bBridgePaused = false;
	bool bMouseGrabActive = false;
	bool bPendingMouseDrag = false;
	bool bCameraLookActive = false;
	bool bReplicaCameraBound = false;
	FVector2D MousePressPositionPx = FVector2D::ZeroVector;
	FVector GrabPlaneStartPointCm = FVector::ZeroVector;
	FVector GrabPlaneNormalCm = FVector::ForwardVector;
	FString ActiveGrabId;
	FString PendingDragObjectId;
	TArray<FString> SelectedObjectIds;
	FVector LastGrabTargetM = FVector::ZeroVector;

	void HandleImpulseKey();
	void HandleResetKey();
	void HandlePauseKey();
	void HandleLiftDropKey();
	void HandleSelectPressed();
	void HandleSelectReleased();
	void TryStartMouseGrabIfDragged();
	void HandleCameraLookPressed();
	void HandleCameraLookReleased();
	void ActivateReplicaCamera();
	void HandleClearSelection();
	void UpdateMouseGrabTarget();
	bool ProjectMouseToGrabPlane(FVector& OutPointCm) const;
	void UpdateFreeCamera(float DeltaSeconds);
	void UpdateSelectionOverlay();
	class AMuJoCoBridgeDemoActor* SelectObjectAtCursor(bool bAdditiveSelection);
	void UpdateSelectionHighlight();
	class UMuJoCoStateReceiverComponent* FindBridgeReceiver();
	class AMuJoCoBridgeDemoActor* FindSelectedActor();
	class AMuJoCoBridgeDemoActor* FindActorByObjectId(const FString& ObjectId) const;
};
