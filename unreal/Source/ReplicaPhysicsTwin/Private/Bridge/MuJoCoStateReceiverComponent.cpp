#include "Bridge/MuJoCoStateReceiverComponent.h"

#include "Bridge/MuJoCoBridgeDemoActor.h"
#include "Components/PrimitiveComponent.h"
#include "Dom/JsonObject.h"
#include "GameFramework/Actor.h"
#include "EngineUtils.h"
#include "Interfaces/IPv4/IPv4Address.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "SocketSubsystem.h"
#include "Sockets.h"

DEFINE_LOG_CATEGORY(LogMuJoCoBridge);

UMuJoCoStateReceiverComponent::UMuJoCoStateReceiverComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickInterval = 0.0f;
}

void UMuJoCoStateReceiverComponent::BeginPlay()
{
	Super::BeginPlay();
	NextReconnectTime = 0.0;
	if (bAutoConnect)
	{
		TryConnect();
	}
}

void UMuJoCoStateReceiverComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	CloseSocket(TEXT("component ended play"));
	Super::EndPlay(EndPlayReason);
}

void UMuJoCoStateReceiverComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	const double CurrentTime = GetWorld() != nullptr ? GetWorld()->GetTimeSeconds() : 0.0;
	if (Socket == nullptr)
	{
		if (bAutoConnect && CurrentTime >= NextReconnectTime)
		{
			TryConnect();
		}
		return;
	}
	ReadAvailable();
}

bool UMuJoCoStateReceiverComponent::TryConnect()
{
	if (Socket != nullptr)
	{
		return true;
	}

	ISocketSubsystem* SocketSubsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
	if (SocketSubsystem == nullptr)
	{
		ScheduleReconnect();
		return false;
	}

	bool bValidAddress = false;
	TSharedRef<FInternetAddr> Address = SocketSubsystem->CreateInternetAddr();
	Address->SetIp(*Host, bValidAddress);
	Address->SetPort(Port);
	if (!bValidAddress)
	{
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Invalid bridge host: %s"), *Host);
		ScheduleReconnect();
		return false;
	}

	Socket = SocketSubsystem->CreateSocket(NAME_Stream, TEXT("MuJoCoBridgeReceiver"), false);
	if (Socket == nullptr)
	{
		ScheduleReconnect();
		return false;
	}

	Socket->SetNonBlocking(false);
	if (!Socket->Connect(*Address))
	{
		CloseSocket(TEXT("connect failed"));
		ScheduleReconnect();
		return false;
	}
	Socket->SetNonBlocking(true);
	ReceiveBuffer.Reset();
	UE_LOG(LogMuJoCoBridge, Log, TEXT("Connected to MuJoCo bridge %s:%d for object %s"), *Host, Port, *ObjectId);
	return true;
}

void UMuJoCoStateReceiverComponent::CloseSocket(const TCHAR* Reason)
{
	if (Socket == nullptr)
	{
		return;
	}
	ISocketSubsystem* SocketSubsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
	if (SocketSubsystem != nullptr)
	{
		SocketSubsystem->DestroySocket(Socket);
	}
	Socket = nullptr;
	ReceiveBuffer.Reset();
	UE_LOG(LogMuJoCoBridge, Warning, TEXT("MuJoCo bridge connection closed: %s"), Reason);
}

void UMuJoCoStateReceiverComponent::ScheduleReconnect()
{
	const double CurrentTime = GetWorld() != nullptr ? GetWorld()->GetTimeSeconds() : 0.0;
	NextReconnectTime = CurrentTime + FMath::Max(0.05f, ReconnectIntervalSeconds);
}

void UMuJoCoStateReceiverComponent::ReadAvailable()
{
	if (Socket == nullptr)
	{
		return;
	}

	uint32 PendingBytes = 0;
	while (Socket->HasPendingData(PendingBytes))
	{
		const uint32 ReadSize = FMath::Min(PendingBytes, 64u * 1024u);
		TArray<uint8> Chunk;
		Chunk.SetNumUninitialized(static_cast<int32>(ReadSize));
		int32 BytesRead = 0;
		if (!Socket->Recv(Chunk.GetData(), static_cast<int32>(ReadSize), BytesRead, ESocketReceiveFlags::None))
		{
			CloseSocket(TEXT("receive failed"));
			ScheduleReconnect();
			return;
		}
		if (BytesRead <= 0)
		{
			break;
		}
		ReceiveBuffer.Append(Chunk.GetData(), BytesRead);
		if (ReceiveBuffer.Num() > 1024 * 1024)
		{
			CloseSocket(TEXT("receive buffer exceeded 1 MiB"));
			ScheduleReconnect();
			return;
		}
	}

	while (true)
	{
		int32 NewlineIndex = INDEX_NONE;
		for (int32 Index = 0; Index < ReceiveBuffer.Num(); ++Index)
		{
			if (ReceiveBuffer[Index] == static_cast<uint8>('\n'))
			{
				NewlineIndex = Index;
				break;
			}
		}
		if (NewlineIndex == INDEX_NONE)
		{
			break;
		}

		TArray<uint8> LineBytes;
		LineBytes.Append(ReceiveBuffer.GetData(), NewlineIndex);
		LineBytes.Add(0);
		ReceiveBuffer.RemoveAt(0, NewlineIndex + 1, EAllowShrinking::No);
		ProcessLine(UTF8_TO_TCHAR(reinterpret_cast<const ANSICHAR*>(LineBytes.GetData())));
	}
}

void UMuJoCoStateReceiverComponent::ProcessLine(const FString& Line)
{
	TSharedPtr<FJsonObject> RootObject;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Line);
	if (!FJsonSerializer::Deserialize(Reader, RootObject) || !RootObject.IsValid())
	{
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Rejected bridge message: invalid JSON"));
		return;
	}

	FString MessageType;
	if (!RootObject->TryGetStringField(TEXT("type"), MessageType))
	{
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Rejected bridge message: missing type"));
		return;
	}
	if (MessageType == TEXT("ack") || MessageType == TEXT("command"))
	{
		FString CommandName;
		FString GrabId;
		RootObject->TryGetStringField(TEXT("command"), CommandName);
		RootObject->TryGetStringField(TEXT("grab_id"), GrabId);
		UE_LOG(LogMuJoCoBridge, Log, TEXT("Bridge command acknowledged: %s%s"), *CommandName, GrabId.IsEmpty() ? TEXT("") : *FString::Printf(TEXT(" grab_id=%s"), *GrabId));
		return;
	}
	if (MessageType == TEXT("error"))
	{
		FString ErrorCode;
		FString ErrorMessage;
		RootObject->TryGetStringField(TEXT("error_code"), ErrorCode);
		RootObject->TryGetStringField(TEXT("message"), ErrorMessage);
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Bridge command rejected: %s - %s"), *ErrorCode, *ErrorMessage);
		return;
	}
	if (MessageType != TEXT("state"))
	{
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Rejected bridge message: unsupported type %s"), *MessageType);
		return;
	}

	FMuJoCoStateMessage Message;
	FString Error;
	if (!FMuJoCoStateMessage::ParseLine(Line, Message, &Error))
	{
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Rejected MuJoCo state: %s"), *Error);
		return;
	}
	if (!FMuJoCoStateMessage::ShouldApplySequence(LastAppliedSeq, Message.Seq))
	{
		UE_LOG(LogMuJoCoBridge, Verbose, TEXT("Ignored stale MuJoCo state seq=%lld last=%lld"), Message.Seq, LastAppliedSeq);
		return;
	}
	ApplyState(Message);
}

void UMuJoCoStateReceiverComponent::ApplyState(const FMuJoCoStateMessage& Message)
{
	bool bAppliedAnyObject = false;
	for (const FMuJoCoObjectState& Object : Message.Objects)
	{
		if (GetWorld() == nullptr)
		{
			continue;
		}
		for (TActorIterator<AMuJoCoBridgeDemoActor> It(GetWorld()); It; ++It)
		{
			AMuJoCoBridgeDemoActor* VisualActor = *It;
			if (VisualActor != nullptr && VisualActor->GetBridgeObjectId() == Object.ObjectId)
			{
				VisualActor->ApplyMuJoCoState(Object);
				bAppliedAnyObject = true;
				break;
			}
		}
	}
	LatestState = Message;
	LastAppliedSeq = Message.Seq;
	if (!bAppliedAnyObject)
	{
		UE_LOG(LogMuJoCoBridge, Warning, TEXT("State seq=%lld did not contain a spawned visual object"), Message.Seq);
	}
}

bool UMuJoCoStateReceiverComponent::SendCommand(const TSharedRef<FJsonObject>& Command)
{
	if (Socket == nullptr)
	{
		return false;
	}

	FString JsonLine;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&JsonLine);
	if (!FJsonSerializer::Serialize(Command, Writer))
	{
		return false;
	}
	JsonLine.AppendChar(TEXT('\n'));
	FTCHARToUTF8 Converter(*JsonLine);
	int32 BytesSent = 0;
	if (!Socket->Send(reinterpret_cast<const uint8*>(Converter.Get()), Converter.Length(), BytesSent) || BytesSent != Converter.Length())
	{
		CloseSocket(TEXT("send failed"));
		ScheduleReconnect();
		return false;
	}
	return true;
}

bool UMuJoCoStateReceiverComponent::SendApplyImpulse(FVector ImpulseNs)
{
	return SendApplyImpulseForObject(ObjectId, ImpulseNs);
}

bool UMuJoCoStateReceiverComponent::SendApplyImpulseForObject(const FString& InObjectId, FVector ImpulseNs)
{
	TSharedRef<FJsonObject> Command = MakeShared<FJsonObject>();
	Command->SetStringField(TEXT("type"), TEXT("command"));
	Command->SetNumberField(TEXT("schema_version"), 2);
	Command->SetStringField(TEXT("command"), TEXT("apply_impulse"));
	Command->SetStringField(TEXT("object_id"), InObjectId);
	TArray<TSharedPtr<FJsonValue>> Values;
	Values.Add(MakeShared<FJsonValueNumber>(ImpulseNs.X));
	Values.Add(MakeShared<FJsonValueNumber>(ImpulseNs.Y));
	Values.Add(MakeShared<FJsonValueNumber>(ImpulseNs.Z));
	Command->SetArrayField(TEXT("impulse_ns"), Values);
	return SendCommand(Command);
}

bool UMuJoCoStateReceiverComponent::SendReset()
{
	TSharedRef<FJsonObject> Command = MakeShared<FJsonObject>();
	Command->SetStringField(TEXT("type"), TEXT("command"));
	Command->SetNumberField(TEXT("schema_version"), 2);
	Command->SetStringField(TEXT("command"), TEXT("reset"));
	return SendCommand(Command);
}

bool UMuJoCoStateReceiverComponent::SendPause(bool bPaused)
{
	TSharedRef<FJsonObject> Command = MakeShared<FJsonObject>();
	Command->SetStringField(TEXT("type"), TEXT("command"));
	Command->SetNumberField(TEXT("schema_version"), 2);
	Command->SetStringField(TEXT("command"), TEXT("pause"));
	Command->SetBoolField(TEXT("paused"), bPaused);
	return SendCommand(Command);
}

bool UMuJoCoStateReceiverComponent::SendLiftDrop(float LiftHeightM)
{
	return SendLiftDropForObject(ObjectId, LiftHeightM);
}

bool UMuJoCoStateReceiverComponent::SendLiftDropForObject(const FString& InObjectId, float LiftHeightM)
{
	if (!FMath::IsFinite(LiftHeightM) || LiftHeightM < 0.0f || LiftHeightM > 1.0f)
	{
		return false;
	}
	TSharedRef<FJsonObject> Command = MakeShared<FJsonObject>();
	Command->SetStringField(TEXT("type"), TEXT("command"));
	Command->SetNumberField(TEXT("schema_version"), 2);
	Command->SetStringField(TEXT("command"), TEXT("lift_drop"));
	Command->SetStringField(TEXT("object_id"), InObjectId);
	Command->SetNumberField(TEXT("lift_height_m"), LiftHeightM);
	return SendCommand(Command);
}

bool UMuJoCoStateReceiverComponent::SendGrabBegin(const TArray<FString>& ObjectIds, FVector AnchorM, FString& OutGrabId)
{
	if (ObjectIds.Num() == 0 || AnchorM.ContainsNaN())
	{
		return false;
	}
	OutGrabId = FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphens);
	TSharedRef<FJsonObject> Command = MakeShared<FJsonObject>();
	Command->SetStringField(TEXT("type"), TEXT("command"));
	Command->SetNumberField(TEXT("schema_version"), 2);
	Command->SetStringField(TEXT("command"), TEXT("grab_begin"));
	Command->SetStringField(TEXT("client_grab_id"), OutGrabId);
	TArray<TSharedPtr<FJsonValue>> JsonIds;
	for (const FString& ObjectIdValue : ObjectIds)
	{
		JsonIds.Add(MakeShared<FJsonValueString>(ObjectIdValue));
	}
	Command->SetArrayField(TEXT("object_ids"), JsonIds);
	TArray<TSharedPtr<FJsonValue>> AnchorValues;
	AnchorValues.Add(MakeShared<FJsonValueNumber>(AnchorM.X));
	AnchorValues.Add(MakeShared<FJsonValueNumber>(AnchorM.Y));
	AnchorValues.Add(MakeShared<FJsonValueNumber>(AnchorM.Z));
	Command->SetArrayField(TEXT("anchor_m"), AnchorValues);
	return SendCommand(Command);
}

bool UMuJoCoStateReceiverComponent::SendGrabUpdate(const FString& GrabId, FVector TargetPositionM, const FQuat& TargetRotation)
{
	if (GrabId.IsEmpty() || TargetPositionM.ContainsNaN())
	{
		return false;
	}
	const FQuat NormalizedRotation = TargetRotation.GetNormalized();
	TSharedRef<FJsonObject> Command = MakeShared<FJsonObject>();
	Command->SetStringField(TEXT("type"), TEXT("command"));
	Command->SetNumberField(TEXT("schema_version"), 2);
	Command->SetStringField(TEXT("command"), TEXT("grab_update"));
	Command->SetStringField(TEXT("grab_id"), GrabId);
	TArray<TSharedPtr<FJsonValue>> PositionValues;
	PositionValues.Add(MakeShared<FJsonValueNumber>(TargetPositionM.X));
	PositionValues.Add(MakeShared<FJsonValueNumber>(TargetPositionM.Y));
	PositionValues.Add(MakeShared<FJsonValueNumber>(TargetPositionM.Z));
	Command->SetArrayField(TEXT("target_position_m"), PositionValues);
	TArray<TSharedPtr<FJsonValue>> QuaternionValues;
	QuaternionValues.Add(MakeShared<FJsonValueNumber>(NormalizedRotation.W));
	QuaternionValues.Add(MakeShared<FJsonValueNumber>(NormalizedRotation.X));
	QuaternionValues.Add(MakeShared<FJsonValueNumber>(NormalizedRotation.Y));
	QuaternionValues.Add(MakeShared<FJsonValueNumber>(NormalizedRotation.Z));
	Command->SetArrayField(TEXT("target_quaternion_wxyz"), QuaternionValues);
	return SendCommand(Command);
}

bool UMuJoCoStateReceiverComponent::SendGrabEnd(const FString& GrabId)
{
	if (GrabId.IsEmpty())
	{
		return false;
	}
	TSharedRef<FJsonObject> Command = MakeShared<FJsonObject>();
	Command->SetStringField(TEXT("type"), TEXT("command"));
	Command->SetNumberField(TEXT("schema_version"), 2);
	Command->SetStringField(TEXT("command"), TEXT("grab_end"));
	Command->SetStringField(TEXT("grab_id"), GrabId);
	return SendCommand(Command);
}
