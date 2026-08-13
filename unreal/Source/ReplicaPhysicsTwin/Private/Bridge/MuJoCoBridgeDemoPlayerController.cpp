#include "Bridge/MuJoCoBridgeDemoPlayerController.h"

#include "Bridge/MuJoCoBridgeDemoActor.h"
#include "Bridge/MuJoCoStateReceiverComponent.h"
#include "Camera/CameraActor.h"
#include "EngineUtils.h"
#include "Engine/Engine.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"

AMuJoCoBridgeDemoPlayerController::AMuJoCoBridgeDemoPlayerController()
{
	PrimaryActorTick.bCanEverTick = true;
	bShowMouseCursor = true;
	bEnableClickEvents = true;
	bEnableMouseOverEvents = true;
}

void AMuJoCoBridgeDemoPlayerController::BeginPlay()
{
	Super::BeginPlay();
	// Keep the runtime viewport as the input owner even while the cursor is
	// visible.  GameAndUI lets Slate/editor focus win, which makes both
	// keyboard movement and controller-level mouse bindings appear dead.
	FInputModeGameOnly InputMode;
	InputMode.SetConsumeCaptureMouseDown(false);
	SetInputMode(InputMode);
	SetIgnoreLookInput(false);
	SetIgnoreMoveInput(false);
	ActivateReplicaCamera();
}

void AMuJoCoBridgeDemoPlayerController::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bReplicaCameraBound)
	{
		ActivateReplicaCamera();
	}
	UpdateFreeCamera(DeltaSeconds);
	if (bPendingMouseDrag)
	{
		TryStartMouseGrabIfDragged();
	}
	if (bMouseGrabActive)
	{
		UpdateMouseGrabTarget();
	}
	UpdateSelectionOverlay();
}

void AMuJoCoBridgeDemoPlayerController::SetupInputComponent()
{
	Super::SetupInputComponent();

	if (InputComponent == nullptr)
	{
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Phase 3 input setup failed: PlayerController has no InputComponent"));
		return;
	}

	InputComponent->BindKey(EKeys::I, IE_Pressed, this, &AMuJoCoBridgeDemoPlayerController::HandleImpulseKey);
	InputComponent->BindKey(EKeys::R, IE_Pressed, this, &AMuJoCoBridgeDemoPlayerController::HandleResetKey);
	InputComponent->BindKey(EKeys::P, IE_Pressed, this, &AMuJoCoBridgeDemoPlayerController::HandlePauseKey);
	InputComponent->BindKey(EKeys::T, IE_Pressed, this, &AMuJoCoBridgeDemoPlayerController::HandleLiftDropKey);
	InputComponent->BindKey(EKeys::LeftMouseButton, IE_Pressed, this, &AMuJoCoBridgeDemoPlayerController::HandleSelectPressed);
	InputComponent->BindKey(EKeys::LeftMouseButton, IE_Released, this, &AMuJoCoBridgeDemoPlayerController::HandleSelectReleased);
	InputComponent->BindKey(EKeys::RightMouseButton, IE_Pressed, this, &AMuJoCoBridgeDemoPlayerController::HandleCameraLookPressed);
	InputComponent->BindKey(EKeys::RightMouseButton, IE_Released, this, &AMuJoCoBridgeDemoPlayerController::HandleCameraLookReleased);
	InputComponent->BindKey(EKeys::Escape, IE_Pressed, this, &AMuJoCoBridgeDemoPlayerController::HandleClearSelection);
	UE_LOG(LogMuJoCoBridge, Log, TEXT("MuJoCo controls: I=selected impulse, R=reset, P=pause, T=selected lift/drop, click=select, Shift+click=add/remove selection, click-drag=push clicked object only, RMB+mouse=look, WASD=move, Q/E=down/up, Shift=sprint"));
}

void AMuJoCoBridgeDemoPlayerController::ActivateReplicaCamera()
{
	if (bReplicaCameraBound || GetWorld() == nullptr)
	{
		return;
	}

	for (TActorIterator<ACameraActor> It(GetWorld()); It; ++It)
	{
		if (!It->ActorHasTag(TEXT("ReplicaRuntimeCamera")))
		{
			continue;
		}

		SetViewTarget(*It);
		bReplicaCameraBound = true;
		UE_LOG(LogMuJoCoBridge, Log, TEXT("Replica runtime camera activated location=(%.1f,%.1f,%.1f)"),
			It->GetActorLocation().X,
			It->GetActorLocation().Y,
			It->GetActorLocation().Z);
		return;
	}
}

void AMuJoCoBridgeDemoPlayerController::HandleCameraLookPressed()
{
	if (bMouseGrabActive)
	{
		return;
	}
	bCameraLookActive = true;
	bShowMouseCursor = false;
	SetInputMode(FInputModeGameOnly());
}

void AMuJoCoBridgeDemoPlayerController::HandleCameraLookReleased()
{
	bCameraLookActive = false;
	bShowMouseCursor = true;
	FInputModeGameOnly InputMode;
	InputMode.SetConsumeCaptureMouseDown(false);
	SetInputMode(InputMode);
}

void AMuJoCoBridgeDemoPlayerController::UpdateFreeCamera(float DeltaSeconds)
{
	ACameraActor* Camera = Cast<ACameraActor>(GetViewTarget());
	if (Camera == nullptr)
	{
		return;
	}

	FVector Forward = Camera->GetActorForwardVector();
	Forward.Z = 0.0f;
	Forward = Forward.GetSafeNormal();
	FVector Right = Camera->GetActorRightVector();
	Right.Z = 0.0f;
	Right = Right.GetSafeNormal();
	FVector Movement = FVector::ZeroVector;
	if (IsInputKeyDown(EKeys::W))
	{
		Movement += Forward;
	}
	if (IsInputKeyDown(EKeys::S))
	{
		Movement -= Forward;
	}
	if (IsInputKeyDown(EKeys::D))
	{
		Movement += Right;
	}
	if (IsInputKeyDown(EKeys::A))
	{
		Movement -= Right;
	}
	if (IsInputKeyDown(EKeys::E))
	{
		Movement.Z += 1.0f;
	}
	if (IsInputKeyDown(EKeys::Q))
	{
		Movement.Z -= 1.0f;
	}
	if (!Movement.IsNearlyZero())
	{
		const float SpeedCmPerSecond = IsInputKeyDown(EKeys::LeftShift) || IsInputKeyDown(EKeys::RightShift) ? 480.0f : 220.0f;
		Camera->AddActorWorldOffset(Movement.GetSafeNormal() * SpeedCmPerSecond * DeltaSeconds, false);
	}

	if (!bCameraLookActive)
	{
		return;
	}

	float MouseDeltaX = 0.0f;
	float MouseDeltaY = 0.0f;
	GetInputMouseDelta(MouseDeltaX, MouseDeltaY);
	if (FMath::IsNearlyZero(MouseDeltaX) && FMath::IsNearlyZero(MouseDeltaY))
	{
		return;
	}
	FRotator Rotation = Camera->GetActorRotation();
	Rotation.Yaw += MouseDeltaX * 0.12f;
	Rotation.Pitch = FMath::Clamp(Rotation.Pitch - MouseDeltaY * 0.12f, -80.0f, 80.0f);
	Rotation.Roll = 0.0f;
	Camera->SetActorRotation(Rotation);
}

void AMuJoCoBridgeDemoPlayerController::HandleImpulseKey()
{
	if (UMuJoCoStateReceiverComponent* Receiver = FindBridgeReceiver())
	{
		const TArray<FString>& Targets = SelectedObjectIds;
		if (Targets.Num() == 0)
		{
			const bool bSent = Receiver->SendApplyImpulse(FVector(0.1f, 0.0f, 0.0f));
			UE_LOG(LogMuJoCoBridge, Log, TEXT("Phase 3 I key received: apply_impulse [+X] sent=%s connected=%s"),
				bSent ? TEXT("true") : TEXT("false"),
				Receiver->IsConnected() ? TEXT("true") : TEXT("false"));
			return;
		}
		for (const FString& Target : Targets)
		{
			Receiver->SendApplyImpulseForObject(Target, FVector(0.1f, 0.0f, 0.0f));
		}
		UE_LOG(LogMuJoCoBridge, Log, TEXT("I key applied MuJoCo impulse to %d selected objects"), Targets.Num());
		return;
	}
	UE_LOG(LogMuJoCoBridge, Warning, TEXT("Phase 3 I key received but demo actor was not found"));
}

void AMuJoCoBridgeDemoPlayerController::HandleResetKey()
{
	if (UMuJoCoStateReceiverComponent* Receiver = FindBridgeReceiver())
	{
		const bool bSent = Receiver->SendReset();
		UE_LOG(LogMuJoCoBridge, Log, TEXT("R key reset sent=%s connected=%s"),
			bSent ? TEXT("true") : TEXT("false"),
			Receiver->IsConnected() ? TEXT("true") : TEXT("false"));
		return;
	}
	UE_LOG(LogMuJoCoBridge, Warning, TEXT("Phase 3 R key received but demo actor was not found"));
}

void AMuJoCoBridgeDemoPlayerController::HandlePauseKey()
{
	bBridgePaused = !bBridgePaused;
	if (UMuJoCoStateReceiverComponent* Receiver = FindBridgeReceiver())
	{
		const bool bSent = Receiver->SendPause(bBridgePaused);
		UE_LOG(LogMuJoCoBridge, Log, TEXT("P key paused=%s sent=%s connected=%s"),
			bBridgePaused ? TEXT("true") : TEXT("false"),
			bSent ? TEXT("true") : TEXT("false"),
			Receiver->IsConnected() ? TEXT("true") : TEXT("false"));
		return;
	}
	UE_LOG(LogMuJoCoBridge, Warning, TEXT("Phase 3 P key received but demo actor was not found"));
}

void AMuJoCoBridgeDemoPlayerController::HandleLiftDropKey()
{
	if (UMuJoCoStateReceiverComponent* Receiver = FindBridgeReceiver())
	{
		if (SelectedObjectIds.Num() == 0)
		{
			const bool bSent = Receiver->SendLiftDrop(0.30f);
			UE_LOG(LogMuJoCoBridge, Log, TEXT("T key lift_drop default object sent=%s connected=%s"),
				bSent ? TEXT("true") : TEXT("false"),
				Receiver->IsConnected() ? TEXT("true") : TEXT("false"));
			return;
		}
		for (const FString& Target : SelectedObjectIds)
		{
			Receiver->SendLiftDropForObject(Target, 0.30f);
		}
		UE_LOG(LogMuJoCoBridge, Log, TEXT("T key lift_drop sent to %d selected objects"), SelectedObjectIds.Num());
		return;
	}
	UE_LOG(LogMuJoCoBridge, Warning, TEXT("Phase 6 T key received but dynamic actor was not found"));
}

UMuJoCoStateReceiverComponent* AMuJoCoBridgeDemoPlayerController::FindBridgeReceiver()
{
	UMuJoCoStateReceiverComponent* FirstReceiver = nullptr;
	for (TActorIterator<AMuJoCoBridgeDemoActor> It(GetWorld()); It; ++It)
	{
		if (UMuJoCoStateReceiverComponent* Receiver = It->GetReceiver())
		{
			if (FirstReceiver == nullptr)
			{
				FirstReceiver = Receiver;
			}
			if (Receiver->IsConnected())
			{
				return Receiver;
			}
		}
	}
	return FirstReceiver;
}

AMuJoCoBridgeDemoActor* AMuJoCoBridgeDemoPlayerController::FindSelectedActor()
{
	if (SelectedObjectIds.Num() == 0)
	{
		return nullptr;
	}
	return FindActorByObjectId(SelectedObjectIds[0]);
}

AMuJoCoBridgeDemoActor* AMuJoCoBridgeDemoPlayerController::FindActorByObjectId(const FString& ObjectId) const
{
	for (TActorIterator<AMuJoCoBridgeDemoActor> It(GetWorld()); It; ++It)
	{
		if (It->GetBridgeObjectId() == ObjectId)
		{
			return *It;
		}
	}
	return nullptr;
}

void AMuJoCoBridgeDemoPlayerController::UpdateSelectionHighlight()
{
	for (TActorIterator<AMuJoCoBridgeDemoActor> It(GetWorld()); It; ++It)
	{
		It->SetSelected(SelectedObjectIds.Contains(It->GetBridgeObjectId()));
	}
}

AMuJoCoBridgeDemoActor* AMuJoCoBridgeDemoPlayerController::SelectObjectAtCursor(bool bAdditiveSelection)
{
	float MouseX = 0.0f;
	float MouseY = 0.0f;
	if (!GetMousePosition(MouseX, MouseY))
	{
		return nullptr;
	}
	AMuJoCoBridgeDemoActor* BestActor = nullptr;
	float BestDistanceSquared = FMath::Square(120.0f);
	for (TActorIterator<AMuJoCoBridgeDemoActor> It(GetWorld()); It; ++It)
	{
		if (It->GetBridgeObjectId().IsEmpty())
		{
			continue;
		}

		// The runtime semantic meshes deliberately have no collision: physics
		// collision belongs to MuJoCo, not Unreal.  A cursor line trace would
		// therefore never hit these actors.  Project all eight corners of the
		// rendered actor bounds and pick against the resulting screen rectangle.
		const FBox WorldBounds = It->GetComponentsBoundingBox(true);
		if (!WorldBounds.IsValid)
		{
			continue;
		}
		const FVector Min = WorldBounds.Min;
		const FVector Max = WorldBounds.Max;
		const FVector Corners[8] =
		{
			FVector(Min.X, Min.Y, Min.Z), FVector(Min.X, Min.Y, Max.Z),
			FVector(Min.X, Max.Y, Min.Z), FVector(Min.X, Max.Y, Max.Z),
			FVector(Max.X, Min.Y, Min.Z), FVector(Max.X, Min.Y, Max.Z),
			FVector(Max.X, Max.Y, Min.Z), FVector(Max.X, Max.Y, Max.Z)
		};
		float ScreenMinX = BIG_NUMBER;
		float ScreenMinY = BIG_NUMBER;
		float ScreenMaxX = -BIG_NUMBER;
		float ScreenMaxY = -BIG_NUMBER;
		bool bProjectedAnyCorner = false;
		for (const FVector& Corner : Corners)
		{
			FVector2D ScreenPosition;
			if (!ProjectWorldLocationToScreen(Corner, ScreenPosition, true))
			{
				continue;
			}
			bProjectedAnyCorner = true;
			ScreenMinX = FMath::Min(ScreenMinX, ScreenPosition.X);
			ScreenMinY = FMath::Min(ScreenMinY, ScreenPosition.Y);
			ScreenMaxX = FMath::Max(ScreenMaxX, ScreenPosition.X);
			ScreenMaxY = FMath::Max(ScreenMaxY, ScreenPosition.Y);
		}
		if (!bProjectedAnyCorner)
		{
			continue;
		}

		const float DistanceX = MouseX < ScreenMinX ? ScreenMinX - MouseX : MouseX > ScreenMaxX ? MouseX - ScreenMaxX : 0.0f;
		const float DistanceY = MouseY < ScreenMinY ? ScreenMinY - MouseY : MouseY > ScreenMaxY ? MouseY - ScreenMaxY : 0.0f;
		const float PickRadius = 120.0f;
		const float DistanceSquared = FMath::Square(DistanceX) + FMath::Square(DistanceY);
		if (DistanceSquared <= FMath::Square(PickRadius) && DistanceSquared <= BestDistanceSquared)
		{
			if (DistanceSquared < BestDistanceSquared)
			{
				BestDistanceSquared = DistanceSquared;
				BestActor = *It;
			}
		}
	}
	if (BestActor == nullptr)
	{
		if (!bAdditiveSelection)
		{
			SelectedObjectIds.Reset();
			UpdateSelectionHighlight();
		}
		return nullptr;
	}

	const FString SelectedId = BestActor->GetBridgeObjectId();
	if (bAdditiveSelection)
	{
		if (SelectedObjectIds.Contains(SelectedId))
		{
			SelectedObjectIds.Remove(SelectedId);
		}
		else
		{
			SelectedObjectIds.Add(SelectedId);
		}
		UpdateSelectionHighlight();
		UE_LOG(LogMuJoCoBridge, Log, TEXT("Shift+click selection-only: %d objects; toggled=%s"), SelectedObjectIds.Num(), *SelectedId);
		return BestActor;
	}

	// A normal click on a new object replaces the selection.  A normal click
	// on an already-selected object keeps the multi-selection, but the later
	// physical drag is deliberately scoped to the object under the cursor.
	// This prevents an accidental click on a bike from also moving a garment
	// selected earlier with Shift+click.
	if (!SelectedObjectIds.Contains(SelectedId))
	{
		SelectedObjectIds.Reset();
		SelectedObjectIds.Add(SelectedId);
	}
	UpdateSelectionHighlight();
	UE_LOG(LogMuJoCoBridge, Log, TEXT("Click selection: %d objects; anchor=%s"), SelectedObjectIds.Num(), *SelectedId);
	return BestActor;
}

void AMuJoCoBridgeDemoPlayerController::HandleSelectPressed()
{
	if (bMouseGrabActive)
	{
		HandleSelectReleased();
	}
	const bool bAdditiveSelection = IsInputKeyDown(EKeys::LeftShift) || IsInputKeyDown(EKeys::RightShift);
	float MouseX = 0.0f;
	float MouseY = 0.0f;
	const bool bMousePositionKnown = GetMousePosition(MouseX, MouseY);
	UE_LOG(LogMuJoCoBridge, Log, TEXT("Left click received mouse=(%.1f,%.1f) known=%s shift=%s"),
		MouseX,
		MouseY,
		bMousePositionKnown ? TEXT("true") : TEXT("false"),
		bAdditiveSelection ? TEXT("true") : TEXT("false"));
	AMuJoCoBridgeDemoActor* PickedActor = SelectObjectAtCursor(bAdditiveSelection);
	if (bAdditiveSelection || PickedActor == nullptr || SelectedObjectIds.Num() == 0)
	{
		return;
	}

	// Selection is not a physics command.  Keep the press pending until the
	// cursor has moved enough to prove that the user intended a push/drag.
	bPendingMouseDrag = true;
	MousePressPositionPx = FVector2D(MouseX, MouseY);
	PendingDragObjectId = PickedActor->GetBridgeObjectId();
}

void AMuJoCoBridgeDemoPlayerController::HandleSelectReleased()
{
	if (bMouseGrabActive)
	{
		if (UMuJoCoStateReceiverComponent* Receiver = FindBridgeReceiver())
		{
			Receiver->SendGrabEnd(ActiveGrabId);
		}
	}
	bMouseGrabActive = false;
	bPendingMouseDrag = false;
	ActiveGrabId.Reset();
	PendingDragObjectId.Reset();
}

void AMuJoCoBridgeDemoPlayerController::TryStartMouseGrabIfDragged()
{
	if (!bPendingMouseDrag || bMouseGrabActive)
	{
		return;
	}
	if (!IsInputKeyDown(EKeys::LeftMouseButton))
	{
		HandleSelectReleased();
		return;
	}

	float MouseX = 0.0f;
	float MouseY = 0.0f;
	if (!GetMousePosition(MouseX, MouseY))
	{
		return;
	}
	constexpr float DragStartThresholdPx = 8.0f;
	const FVector2D MousePosition(MouseX, MouseY);
	if (FVector2D::Distance(MousePosition, MousePressPositionPx) < DragStartThresholdPx)
	{
		return;
	}

	AMuJoCoBridgeDemoActor* AnchorActor = FindActorByObjectId(PendingDragObjectId);
	UMuJoCoStateReceiverComponent* Receiver = FindBridgeReceiver();
	if (AnchorActor == nullptr || Receiver == nullptr)
	{
		HandleSelectReleased();
		return;
	}

	const FMuJoCoObjectState& LatestState = AnchorActor->GetLatestState();
	const FVector AnchorObjectCm = LatestState.bHasProperties
		? LatestState.PositionM * 100.0f
		: AnchorActor->GetActorLocation();
	GrabPlaneStartPointCm = AnchorObjectCm;
	if (ACameraActor* Camera = Cast<ACameraActor>(GetViewTarget()))
	{
		GrabPlaneNormalCm = Camera->GetActorForwardVector().GetSafeNormal();
	}
	else
	{
		GrabPlaneNormalCm = GetControlRotation().Vector().GetSafeNormal();
	}
	if (GrabPlaneNormalCm.IsNearlyZero())
	{
		GrabPlaneNormalCm = FVector::ForwardVector;
	}

	// Use the cursor's point on the camera-facing plane as the grab anchor,
	// not the object's center.  This prevents the first drag frame from
	// injecting a large artificial jump into the spring force.
	FVector AnchorPointCm = AnchorObjectCm;
	ProjectMouseToGrabPlane(AnchorPointCm);
	const FVector AnchorM = AnchorPointCm / 100.0f;
	const TArray<FString> DragObjectIds{ PendingDragObjectId };
	if (Receiver->SendGrabBegin(DragObjectIds, AnchorM, ActiveGrabId))
	{
		bMouseGrabActive = true;
		bPendingMouseDrag = false;
		LastGrabTargetM = AnchorM;
	}
}

void AMuJoCoBridgeDemoPlayerController::HandleClearSelection()
{
	HandleSelectReleased();
	SelectedObjectIds.Reset();
	UpdateSelectionHighlight();
}

void AMuJoCoBridgeDemoPlayerController::UpdateMouseGrabTarget()
{
	if (!bMouseGrabActive)
	{
		return;
	}
	FVector TargetPointCm;
	if (!ProjectMouseToGrabPlane(TargetPointCm))
	{
		return;
	}
	const FVector TargetM = TargetPointCm / 100.0f;
	if (FVector::DistSquared(TargetM, LastGrabTargetM) < FMath::Square(0.002f))
	{
		return;
	}
	if (UMuJoCoStateReceiverComponent* Receiver = FindBridgeReceiver())
	{
		if (Receiver->SendGrabUpdate(ActiveGrabId, TargetM))
		{
			LastGrabTargetM = TargetM;
		}
	}
}

bool AMuJoCoBridgeDemoPlayerController::ProjectMouseToGrabPlane(FVector& OutPointCm) const
{
	float MouseX = 0.0f;
	float MouseY = 0.0f;
	if (!GetMousePosition(MouseX, MouseY))
	{
		return false;
	}
	FVector WorldOrigin;
	FVector WorldDirection;
	if (!DeprojectScreenPositionToWorld(MouseX, MouseY, WorldOrigin, WorldDirection))
	{
		return false;
	}
	const float Denominator = FVector::DotProduct(WorldDirection, GrabPlaneNormalCm);
	if (FMath::IsNearlyZero(Denominator))
	{
		return false;
	}
	const float Distance = FVector::DotProduct(GrabPlaneStartPointCm - WorldOrigin, GrabPlaneNormalCm) / Denominator;
	if (Distance < 0.0f)
	{
		return false;
	}
	OutPointCm = WorldOrigin + WorldDirection * Distance;
	return true;
}

void AMuJoCoBridgeDemoPlayerController::UpdateSelectionOverlay()
{
	const UMuJoCoStateReceiverComponent* BridgeReceiver = FindBridgeReceiver();
	const FString Authority = BridgeReceiver != nullptr && !BridgeReceiver->GetLatestState().PhysicsAuthority.IsEmpty()
		? BridgeReceiver->GetLatestState().PhysicsAuthority
		: TEXT("MuJoCo");
	if (GEngine != nullptr)
	{
		GEngine->AddOnScreenDebugMessage(
			8800,
			0.0f,
			FColor::White,
			TEXT("ReplicaCAD: click = select | Shift+click = add/remove selection | click-drag = push clicked object | RMB+drag = look | WASD/QE = move | R = reset"));
	}
	int32 LocatorIndex = 0;
	for (TActorIterator<AMuJoCoBridgeDemoActor> It(GetWorld()); It; ++It)
	{
		if (GEngine == nullptr || !It->GetLatestState().bHasProperties)
		{
			continue;
		}
		const FMuJoCoObjectState& State = It->GetLatestState();
		// Deformable actors keep an identity actor transform because their mesh
		// vertices are updated directly in world space from MuJoCo.  Use the
		// physics state's representative center here; otherwise cloth is always
		// displayed at (0, 0, 0) even while its vertices are moving.
		const FVector PositionM = State.PositionM;
		const FString DeformationInfo = State.bHasDeformedVertices
			? FString::Printf(TEXT(" | flex_vertices=%d"), State.DeformedVerticesM.Num())
			: TEXT("");
		const FString Locator = FString::Printf(
			TEXT("object[%d] %s | mass=%.2f kg | pos=(%.2f, %.2f, %.2f)m | contacts=%d%s"),
			LocatorIndex + 1,
			*It->GetBridgeObjectId(),
			State.Properties.MassKg,
			PositionM.X,
			PositionM.Y,
			PositionM.Z,
			State.Contacts.Num(),
			*DeformationInfo);
		GEngine->AddOnScreenDebugMessage(8810 + LocatorIndex, 0.0f, FColor::Yellow, Locator);
		++LocatorIndex;
	}
	for (int32 Index = LocatorIndex; Index < 3; ++Index)
	{
		if (GEngine != nullptr)
		{
			GEngine->AddOnScreenDebugMessage(8810 + Index, 0.0f, FColor::White, TEXT(""));
		}
	}
	for (int32 Index = 0; Index < SelectedObjectIds.Num(); ++Index)
	{
		AMuJoCoBridgeDemoActor* Actor = nullptr;
		for (TActorIterator<AMuJoCoBridgeDemoActor> It(GetWorld()); It; ++It)
		{
			if (It->GetBridgeObjectId() == SelectedObjectIds[Index])
			{
				Actor = *It;
				break;
			}
		}
		if (Actor == nullptr)
		{
			continue;
		}
		const FMuJoCoObjectState& State = Actor->GetLatestState();
		if (GEngine == nullptr || !State.bHasProperties)
		{
			continue;
		}
		TArray<FString> ContactIds;
		for (const FMuJoCoContact& Contact : State.Contacts)
		{
			ContactIds.Add(Contact.OtherId);
		}
		const FString ContactSummary = ContactIds.Num() > 0 ? FString::Join(ContactIds, TEXT(",")) : TEXT("none");
		const FString Overlay = FString::Printf(
			TEXT("[%d] %s  source=%s  size=%.3f x %.3f x %.3f m  mass=%.3f kg  v=(%.2f,%.2f,%.2f) m/s  contacts=%d [%s]"),
			Index + 1,
			*Actor->GetBridgeObjectId(),
			*Authority,
			State.Properties.SizeM.X,
			State.Properties.SizeM.Y,
			State.Properties.SizeM.Z,
			State.Properties.MassKg,
			State.LinearVelocityMps.X,
			State.LinearVelocityMps.Y,
			State.LinearVelocityMps.Z,
			State.Contacts.Num(),
			*ContactSummary);
		GEngine->AddOnScreenDebugMessage(9000 + Index, 0.0f, FColor::White, Overlay);
	}
	for (int32 Index = SelectedObjectIds.Num(); Index < 8; ++Index)
	{
		if (GEngine != nullptr)
		{
			GEngine->AddOnScreenDebugMessage(9000 + Index, 0.0f, FColor::White, TEXT(""));
		}
	}
}
